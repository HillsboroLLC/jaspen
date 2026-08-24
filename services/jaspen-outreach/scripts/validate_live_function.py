#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import time
import urllib.error
import urllib.request
from pathlib import Path


REQUIRED_OUTPUT_FIELDS = {
    "overall_qualification": str,
    "product_led_criteria": dict,
    "product_led_user_fit": int,
    "product_led_evidence_coverage": int,
    "enterprise_company_fit": int,
    "purchase_readiness": int,
    "readiness_signals": list,
    "evidence_coverage": int,
    "evidence_confidence": int,
    "recency": int,
    "remit_connection": int,
    "recommended_outreach_angle": str,
    "qualification_rationale": str,
    "enterprise_ready": bool,
    "product_led_review_eligible": bool,
    "review_route": str,
    "route_reason": str,
    "proceed_to_outreach": bool,
    "used_evidence_ids": list,
    "prospect_id": str,
    "evidence_count": int,
    "model": str,
    "prompt_version": str,
    "rubric_version": str,
    "qualified_at": str,
}


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def invoke(
    endpoint: str,
    body: bytes,
    *,
    platform_secret: str | None = None,
    application_secret: str | None = None,
) -> tuple[int, bytes, int]:
    headers = {"Content-Type": "application/json"}
    if platform_secret is not None:
        headers["X-Require-Whisk-Auth"] = platform_secret
    if application_secret is not None:
        headers["X-Jaspen-Outreach-Secret"] = application_secret
    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    started = time.monotonic()
    try:
        with urllib.request.urlopen(request, timeout=190) as response:
            payload = response.read()
            status = response.status
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        status = exc.code
    duration_ms = round((time.monotonic() - started) * 1000)
    return status, payload, duration_ms


def validate_output(raw: bytes, fixture: dict) -> dict[str, object]:
    output = json.loads(raw)
    missing = sorted(set(REQUIRED_OUTPUT_FIELDS) - set(output))
    if missing:
        raise AssertionError(f"Missing output fields: {', '.join(missing)}")
    wrong_types = sorted(
        key
        for key, expected_type in REQUIRED_OUTPUT_FIELDS.items()
        if not isinstance(output[key], expected_type)
    )
    if wrong_types:
        raise AssertionError(f"Wrong output field types: {', '.join(wrong_types)}")

    prospect_id = fixture["prospect"]["id"]
    supplied_ids = {item["id"] for item in fixture["evidence"]}
    used_ids = set(output["used_evidence_ids"])
    if output["prospect_id"] != prospect_id:
        raise AssertionError("Response prospect_id does not match the controlled request")
    if output["evidence_count"] != len(supplied_ids):
        raise AssertionError("Response evidence_count does not match supplied evidence")
    if not used_ids or not used_ids.issubset(supplied_ids):
        raise AssertionError("Response contains missing or unknown evidence references")

    return {
        "overall_qualification": output["overall_qualification"],
        "proceed_to_outreach": output["proceed_to_outreach"],
        "used_evidence_count": len(used_ids),
        "traceability_passed": True,
        "prompt_version": output["prompt_version"],
        "rubric_version": output["rubric_version"],
        "model": output["model"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--fixture", required=True, type=Path)
    args = parser.parse_args()

    env = load_env(args.env_file)
    platform_secret = env["JASPEN_FUNCTION_WEB_SECRET"]
    application_secret = env["JASPEN_OUTREACH_SHARED_SECRET"]
    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    valid_body = json.dumps(fixture, separators=(",", ":")).encode("utf-8")

    report: dict[str, object] = {"endpoint_tested": True}

    status, _, duration = invoke(args.endpoint, valid_body)
    report["missing_gateway_auth"] = {"status": status, "duration_ms": duration}
    if status not in {401, 403}:
        raise AssertionError(f"Missing gateway auth returned {status}")

    status, _, duration = invoke(
        args.endpoint, valid_body, platform_secret=platform_secret
    )
    report["missing_application_auth"] = {"status": status, "duration_ms": duration}
    if status != 401:
        raise AssertionError(f"Missing application auth returned {status}")

    status, _, duration = invoke(
        args.endpoint,
        valid_body,
        platform_secret=platform_secret,
        application_secret="controlled-wrong-secret",
    )
    report["wrong_application_auth"] = {"status": status, "duration_ms": duration}
    if status != 401:
        raise AssertionError(f"Wrong application auth returned {status}")

    status, _, duration = invoke(
        args.endpoint,
        b"{not-json",
        platform_secret=platform_secret,
        application_secret=application_secret,
    )
    report["malformed_json"] = {"status": status, "duration_ms": duration}
    if status != 400:
        raise AssertionError(f"Malformed JSON returned {status}")

    live_runs: list[dict[str, object]] = []
    for label in ("cold_or_initial", "warm"):
        status, raw, duration = invoke(
            args.endpoint,
            valid_body,
            platform_secret=platform_secret,
            application_secret=application_secret,
        )
        if status != 200:
            raise AssertionError(f"Valid {label} qualification returned {status}")
        result = validate_output(raw, fixture)
        result.update({"label": label, "status": status, "duration_ms": duration})
        live_runs.append(result)
    report["live_qualification_runs"] = live_runs
    report["all_function_gates_passed"] = True
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
