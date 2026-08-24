from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import httpx


FUNCTION_DIR = Path(__file__).parents[1] / "packages" / "outreach" / "qualify"
sys.path.insert(0, str(FUNCTION_DIR))
from qualification_core import QualificationResponse

spec = importlib.util.spec_from_file_location(
    "jaspen_outreach_function", FUNCTION_DIR / "__main__.py"
)
function = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(function)


def payload() -> dict:
    return {
        "prospect": {
            "id": "prospect-1",
            "name": "Test Prospect",
            "job_title": "COO",
            "company": "Test Co",
        },
        "evidence": [
            {
                "id": "evidence-1",
                "claim": "The company announced an operational transformation program.",
                "evidence_type": "Company announcement",
                "confidence": 90,
            }
        ],
    }


def event(*, secret: str = "shared-test-secret", body: dict | None = None) -> dict:
    return {
        "http": {
            "method": "POST",
            "path": "/",
            "headers": {
                "content-type": "application/json",
                "x-jaspen-outreach-secret": secret,
                "x-request-id": "request-1",
            },
            "body": json.dumps(body if body is not None else payload()),
            "isBase64Encoded": False,
        }
    }


def successful_result():
    return QualificationResponse.model_validate(
        {
            "overall_qualification": "High",
            "product_led_criteria": {
                "p1_consequential_decision": "strong",
                "p2_human_judgment": "strong",
                "p3_accountability_defensibility": "strong",
                "p4_incomplete_mixed_evidence": "moderate",
                "p5_real_tradeoffs": "strong",
                "p6_near_term_reason": "strong",
                "p7_direct_product_value": "moderate",
                "p8_repeat_use_potential": "strong",
            },
            "product_led_user_fit": 85,
            "product_led_evidence_coverage": 100,
            "enterprise_company_fit": 72,
            "purchase_readiness": 48,
            "readiness_signals": [],
            "evidence_coverage": 76,
            "evidence_confidence": 90,
            "recency": 75,
            "remit_connection": 82,
            "recommended_outreach_angle": "Connect the program to decision clarity.",
            "qualification_rationale": "Evidence evidence-1 supports an active program.",
            "enterprise_ready": True,
            "product_led_review_eligible": True,
            "review_route": "enterprise_ready",
            "route_reason": "Enterprise Company Fit and explicit dated Purchase Readiness meet 55/45.",
            "proceed_to_outreach": True,
            "used_evidence_ids": ["evidence-1"],
            "prospect_id": "prospect-1",
            "evidence_count": 1,
            "model": "gpt-5-mini",
            "prompt_version": "qualification-v3",
            "rubric_version": "jaspen-rubric-v3.0",
            "qualified_at": "2026-08-23T17:00:00Z",
        }
    )


class FunctionContractTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(
            os.environ,
            {"JASPEN_OUTREACH_SHARED_SECRET": "shared-test-secret"},
            clear=False,
        )
        self.env.start()

    def tearDown(self):
        self.env.stop()

    def test_rejects_missing_or_wrong_shared_secret(self):
        response = function.main(event(secret="wrong"))
        self.assertEqual(response["statusCode"], 401)
        self.assertEqual(response["body"], {"error": "Unauthorized"})

    def test_rejects_invalid_request_before_calling_openai(self):
        with patch.object(function, "qualify_with_openai") as qualify:
            response = function.main(event(body={"prospect": {}}))
        self.assertEqual(response["statusCode"], 400)
        qualify.assert_not_called()

    def test_returns_existing_structured_output_contract(self):
        async def qualify(_request):
            return successful_result()

        with patch.object(function, "qualify_with_openai", qualify):
            response = function.main(event())

        self.assertEqual(response["statusCode"], 200)
        self.assertEqual(response["body"]["prospect_id"], "prospect-1")
        self.assertEqual(response["body"]["used_evidence_ids"], ["evidence-1"])
        self.assertEqual(response["body"]["rubric_version"], "jaspen-rubric-v3.0")

    def test_maps_traceability_failure_to_safe_502(self):
        async def qualify(_request):
            raise ValueError("Model referenced evidence that was not supplied")

        with patch.object(function, "qualify_with_openai", qualify):
            response = function.main(event())

        self.assertEqual(response["statusCode"], 502)
        self.assertEqual(response["body"], {"error": "Qualification guardrail failed"})

    def test_maps_openai_http_failure_to_safe_502(self):
        request = httpx.Request("POST", "https://api.openai.com/v1/responses")
        upstream = httpx.Response(
            429, request=request, headers={"x-request-id": "upstream-request"}
        )

        async def qualify(_request):
            raise httpx.HTTPStatusError("rate limited", request=request, response=upstream)

        with patch.object(function, "qualify_with_openai", qualify):
            response = function.main(event())

        self.assertEqual(response["statusCode"], 502)
        self.assertEqual(
            response["body"], {"error": "Qualification provider request failed"}
        )


if __name__ == "__main__":
    unittest.main()
