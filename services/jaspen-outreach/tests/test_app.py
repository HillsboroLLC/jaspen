import json
import os
import unittest
from unittest.mock import patch

import httpx

from app import (
    QualificationModelOutput,
    QualificationRequest,
    _build_openai_payload,
    _validate_traceability,
    qualify_with_openai,
)


def request_payload() -> QualificationRequest:
    return QualificationRequest.model_validate(
        {
            "prospect": {
                "id": "prospect-1",
                "name": "Test Prospect",
                "job_title": "COO",
                "company": "Test Co",
            },
            "evidence": [
                {
                    "id": "evidence-1",
                    "claim": "R2 - Budget cycle: the September 2026 investment committee will prioritize competing initiatives.",
                    "evidence_type": "Purchase Readiness signal",
                    "confidence": 90,
                }
            ],
        }
    )


def model_output(**overrides) -> dict:
    output = {
        "overall_qualification": "High",
        "product_led_criteria": {
            "p1_consequential_decision": "strong",
            "p2_human_judgment": "strong",
            "p3_accountability_defensibility": "strong",
            "p4_incomplete_mixed_evidence": "strong",
            "p5_real_tradeoffs": "strong",
            "p6_near_term_reason": "strong",
            "p7_direct_product_value": "strong",
            "p8_repeat_use_potential": "strong",
        },
        "enterprise_company_fit": 72,
        "readiness_signals": [
            {
                "signal_code": "R2",
                "evidence_id": "evidence-1",
                "signal_date": "2026-09-01",
                "rationale": "The supplied evidence explicitly dates the planning cycle.",
            }
        ],
        "evidence_coverage": 76,
        "evidence_confidence": 90,
        "recency": 75,
        "remit_connection": 82,
        "recommended_outreach_angle": "Connect the transformation program to decision clarity.",
        "qualification_rationale": "Evidence evidence-1 indicates an active program.",
        "used_evidence_ids": ["evidence-1"],
    }
    output.update(overrides)
    return output


class QualificationTests(unittest.IsolatedAsyncioTestCase):
    def test_payload_uses_strict_schema_and_only_supplied_input(self):
        payload = _build_openai_payload(request_payload(), "gpt-5-mini")
        self.assertFalse(payload["store"])
        self.assertTrue(payload["text"]["format"]["strict"])
        input_json = json.loads(payload["input"])
        self.assertEqual(input_json["evidence"][0]["id"], "evidence-1")
        self.assertNotIn("tools", payload)

    def test_unknown_evidence_reference_is_rejected(self):
        output = QualificationModelOutput.model_validate(
            model_output(used_evidence_ids=["invented-evidence"])
        )
        with self.assertRaisesRegex(ValueError, "not supplied"):
            _validate_traceability(request_payload(), output)

    async def test_openai_response_is_parsed_and_audited(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {"type": "output_text", "text": json.dumps(model_output())}
                            ],
                        }
                    ]
                },
                request=request,
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}):
                result = await qualify_with_openai(request_payload(), client=client)

        self.assertEqual(result.prospect_id, "prospect-1")
        self.assertEqual(result.used_evidence_ids, ["evidence-1"])
        self.assertEqual(result.product_led_user_fit, 100)
        self.assertEqual(result.purchase_readiness, 12)
        self.assertEqual(result.review_route, "product_led_review")
        self.assertEqual(result.prompt_version, "qualification-v3")
        self.assertEqual(result.rubric_version, "jaspen-rubric-v3.0")

    def test_dimensions_and_thresholds_are_explicit_and_separate(self):
        payload = _build_openai_payload(request_payload(), "gpt-5-mini")
        instructions = payload["instructions"]
        self.assertIn("Never average", instructions)
        self.assertIn("frozen enterprise thresholds (55/45)", instructions)
        self.assertIn("product-led review threshold (60)", instructions)
        properties = payload["text"]["format"]["schema"]["properties"]
        self.assertIn("product_led_criteria", properties)
        self.assertIn("enterprise_company_fit", properties)
        self.assertIn("readiness_signals", properties)
        self.assertIn("evidence_coverage", properties)

    def test_readiness_discards_undated_or_unmapped_signal(self):
        output = QualificationModelOutput.model_validate(
            model_output(
                readiness_signals=[
                    {
                        "signal_code": "R4",
                        "evidence_id": "evidence-1",
                        "signal_date": "2026-09-01",
                        "rationale": "A senior role exists.",
                    }
                ]
            )
        )
        self.assertEqual(_validate_traceability(request_payload(), output), [])

    async def test_openai_response_discards_invalid_readiness_without_failing(self):
        invalid_output = model_output(
            qualification_rationale=(
                "The role supports product-led fit. The executive appointment is an explicit "
                "R4 readiness signal dated 2026-09-01."
            ),
            readiness_signals=[
                {
                    "signal_code": "R4",
                    "evidence_id": "evidence-1",
                    "signal_date": "2026-09-01",
                    "rationale": "A senior role exists.",
                }
            ]
        )

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(invalid_output),
                                }
                            ],
                        }
                    ]
                },
                request=request,
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}):
                result = await qualify_with_openai(request_payload(), client=client)

        self.assertEqual(result.readiness_signals, [])
        self.assertEqual(result.purchase_readiness, 0)
        self.assertIn("The role supports product-led fit.", result.qualification_rationale)
        self.assertNotIn("executive appointment", result.qualification_rationale)
        self.assertNotIn("R4 readiness signal", result.qualification_rationale)
        self.assertIn(
            "No explicit dated R1-R11 Purchase Readiness signal survived guardrail validation",
            result.qualification_rationale,
        )

    async def test_rationale_names_only_guardrail_accepted_readiness_signals(self):
        mixed_output = model_output(
            qualification_rationale=(
                "The supplied evidence supports the operating context. "
                "R2 is a dated readiness signal. R4 is also a readiness signal."
            ),
            readiness_signals=[
                {
                    "signal_code": "R2",
                    "evidence_id": "evidence-1",
                    "signal_date": "2026-09-01",
                    "rationale": "The supplied evidence explicitly dates the planning cycle.",
                },
                {
                    "signal_code": "R4",
                    "evidence_id": "evidence-1",
                    "signal_date": "2026-09-01",
                    "rationale": "A senior role exists.",
                },
            ],
        )

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "output": [
                        {
                            "type": "message",
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": json.dumps(mixed_output),
                                }
                            ],
                        }
                    ]
                },
                request=request,
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            with patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}):
                result = await qualify_with_openai(request_payload(), client=client)

        self.assertEqual([signal.signal_code for signal in result.readiness_signals], ["R2"])
        self.assertIn("The supplied evidence supports the operating context.", result.qualification_rationale)
        self.assertIn(
            "R2 (evidence evidence-1, dated 2026-09-01)",
            result.qualification_rationale,
        )
        self.assertNotIn("R4", result.qualification_rationale)


if __name__ == "__main__":
    unittest.main()
