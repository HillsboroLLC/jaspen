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



class ReadinessSignalDateAttestationTests(unittest.TestCase):
    """observed_at must corroborate a date, never license an arbitrary one.

    Before this guard existed, a populated observed_at short-circuited validation
    and any model-proposed R1-R11 date was accepted.
    """

    @staticmethod
    def _request(claim, observed_at):
        evidence = {
            "id": "evidence-1",
            "claim": claim,
            "evidence_type": "Purchase Readiness signal",
            "confidence": 90,
        }
        if observed_at is not None:
            evidence["observed_at"] = observed_at
        return QualificationRequest.model_validate(
            {
                "prospect": {
                    "id": "prospect-1",
                    "name": "Test Prospect",
                    "job_title": "COO",
                    "company": "Test Co",
                },
                "evidence": [evidence],
            }
        )

    @staticmethod
    def _signal(signal_date: str) -> dict:
        return {
            "signal_code": "R2",
            "evidence_id": "evidence-1",
            "signal_date": signal_date,
            "rationale": "Readiness assessment under test.",
        }

    def test_observed_date_set_and_readiness_date_supported_is_accepted(self):
        request = self._request(
            "R2 - the 2026-09-01 investment committee will prioritize competing initiatives.",
            "2026-09-01T00:00:00Z",
        )
        output = QualificationModelOutput.model_validate(
            model_output(readiness_signals=[self._signal("2026-09-01")])
        )
        accepted = _validate_traceability(request, output)
        self.assertEqual([s.signal_code for s in accepted], ["R2"])

    def test_observed_date_alone_does_not_validate_an_undated_claim(self):
        # The model can always echo observed_at back; that is not attestation.
        request = self._request(
            "R2 - the investment committee prioritizes competing initiatives.",
            "2026-09-01T00:00:00Z",
        )
        output = QualificationModelOutput.model_validate(
            model_output(readiness_signals=[self._signal("2026-09-01")])
        )
        self.assertEqual(_validate_traceability(request, output), [])

    def test_observed_date_set_but_readiness_date_fabricated_is_rejected(self):
        # observed_at is populated, but the proposed date is attested by nothing.
        request = self._request(
            "R2 - the 2026-09-01 investment committee will prioritize competing initiatives.",
            "2026-09-01T00:00:00Z",
        )
        output = QualificationModelOutput.model_validate(
            model_output(readiness_signals=[self._signal("2026-03-01")])
        )
        self.assertEqual(_validate_traceability(request, output), [])

    def test_observed_date_null_with_valid_dated_claim_is_accepted(self):
        request = self._request(
            "R2 - Budget cycle: the September 2026 investment committee meets to prioritize asks.",
            None,
        )
        output = QualificationModelOutput.model_validate(
            model_output(readiness_signals=[self._signal("2026-09-01")])
        )
        accepted = _validate_traceability(request, output)
        self.assertEqual([s.signal_code for s in accepted], ["R2"])

    def test_observed_date_null_with_unsupported_readiness_date_is_rejected(self):
        request = self._request(
            "R2 - Budget cycle: the investment committee prioritizes competing initiatives.",
            None,
        )
        output = QualificationModelOutput.model_validate(
            model_output(readiness_signals=[self._signal("2026-09-01")])
        )
        self.assertEqual(_validate_traceability(request, output), [])

    def test_evidence_without_a_readiness_signal_does_not_acquire_one(self):
        # No R-code anywhere in the claim; observed_at populated. Nothing may attach.
        request = self._request(
            "The company appointed a new chief transformation officer on 2026-09-01.",
            "2026-09-01T00:00:00Z",
        )
        output = QualificationModelOutput.model_validate(
            model_output(readiness_signals=[self._signal("2026-09-01")])
        )
        self.assertEqual(_validate_traceability(request, output), [])

    def test_observed_date_does_not_license_a_neighbouring_date(self):
        request = self._request(
            "R2 - the investment committee prioritizes competing initiatives.",
            "2026-09-01T00:00:00Z",
        )
        output = QualificationModelOutput.model_validate(
            model_output(readiness_signals=[self._signal("2026-09-02")])
        )
        self.assertEqual(_validate_traceability(request, output), [])


if __name__ == "__main__":
    unittest.main()
