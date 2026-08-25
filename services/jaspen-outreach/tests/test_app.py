import json
import os
import unittest
from unittest.mock import patch

import httpx

from datetime import date

from packages.outreach.qualify.qualification_core import (
    READINESS_RULES,
    ReadinessSignalAssessment,
    calculate_purchase_readiness as _calculate_purchase_readiness,
    determine_review_route as _determine_review_route,
)
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
        "a15_deliberate_decision": "pass",
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
                "signal_date_precision": "month",
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
        self.assertEqual(result.purchase_readiness, 25)  # R2 reconciled to 25 pts
        self.assertEqual(result.review_route, "product_led_review")
        self.assertEqual(result.prompt_version, "qualification-v3.1")
        self.assertEqual(result.rubric_version, "jaspen-rubric-v3.1")

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
                        "signal_date_precision": "month",
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
                    "signal_date_precision": "month",
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
                    "signal_date_precision": "month",
                    "rationale": "The supplied evidence explicitly dates the planning cycle.",
                },
                {
                    "signal_code": "R4",
                    "evidence_id": "evidence-1",
                    "signal_date": "2026-09-01",
                    "signal_date_precision": "month",
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
            "R2 (evidence evidence-1, dated 2026-09 (month precision))",
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
    def _signal(signal_date, precision="day"):
        return {
            "signal_code": "R2",
            "evidence_id": "evidence-1",
            "signal_date": signal_date,
            "signal_date_precision": precision,
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
            model_output(readiness_signals=[self._signal("2026-09-01", "month")])
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



class SignalDatePrecisionTests(unittest.TestCase):
    """A signal may only claim the precision its source actually supplied."""

    @staticmethod
    def _request(claim):
        return QualificationRequest.model_validate({
            "prospect": {"id": "p1", "name": "T", "job_title": "COO", "company": "C"},
            "evidence": [{"id": "evidence-1", "claim": claim,
                          "evidence_type": "Purchase Readiness signal", "confidence": 90}],
        })

    @staticmethod
    def _out(signal_date, precision):
        return QualificationModelOutput.model_validate(model_output(readiness_signals=[{
            "signal_code": "R2", "evidence_id": "evidence-1",
            "signal_date": signal_date, "signal_date_precision": precision,
            "rationale": "Under test.",
        }]))

    MONTH_ONLY = "R2 - the committee meets in April 2026 to prioritize competing initiatives."

    def test_day_precision_is_rejected_on_a_month_only_claim(self):
        # The regression that matters: month-only evidence must not license an invented day.
        accepted = _validate_traceability(
            self._request(self.MONTH_ONLY), self._out("2026-04-01", "day"))
        self.assertEqual(accepted, [])

    def test_month_precision_is_accepted_on_a_month_only_claim(self):
        accepted = _validate_traceability(
            self._request(self.MONTH_ONLY), self._out("2026-04-01", "month"))
        self.assertEqual([s.signal_code for s in accepted], ["R2"])

    def test_day_precision_is_accepted_when_the_day_is_in_the_claim(self):
        claim = "R2 - the committee met on 2026-04-17 to prioritize competing initiatives."
        accepted = _validate_traceability(self._request(claim), self._out("2026-04-17", "day"))
        self.assertEqual([s.signal_code for s in accepted], ["R2"])

    def test_quarter_precision_requires_a_quarter_token(self):
        claim = "R2 - the committee decides in Q2 2026 which initiatives proceed."
        self.assertEqual(
            [s.signal_code for s in _validate_traceability(
                self._request(claim), self._out("2026-04-01", "quarter"))], ["R2"])
        # a day-precision claim over the same quarter-only evidence must fail
        self.assertEqual(
            _validate_traceability(self._request(claim), self._out("2026-04-01", "day")), [])

    def test_coarse_precision_anchors_to_earliest_in_period(self):
        # Conservative anchoring: imprecision must cost readiness, never earn it.
        request = self._request(self.MONTH_ONLY)
        as_of = date(2026, 5, 31)
        month = _calculate_purchase_readiness(
            request,
            [ReadinessSignalAssessment.model_validate({
                "signal_code": "R2", "evidence_id": "evidence-1",
                "signal_date": "2026-04-30", "signal_date_precision": "month",
                "rationale": "x"})],
            as_of=as_of)
        day = _calculate_purchase_readiness(
            request,
            [ReadinessSignalAssessment.model_validate({
                "signal_code": "R2", "evidence_id": "evidence-1",
                "signal_date": "2026-04-30", "signal_date_precision": "day",
                "rationale": "x"})],
            as_of=as_of)
        # month anchors to 2026-04-01, so it has decayed further than the 04-30 day anchor
        self.assertLess(month, day)


class A15HardGateTests(unittest.TestCase):
    """A15 fail is a hard disqualifier, evaluated before any threshold."""

    STRONG = dict(product_led_user_fit=95, enterprise_company_fit=90, purchase_readiness=80)

    def test_high_scoring_prospect_failing_a15_is_held(self):
        ready, plr, route, reason, proceed = _determine_review_route(
            **self.STRONG, a15_deliberate_decision="fail")
        self.assertEqual(route, "hold")
        self.assertFalse(proceed)
        self.assertFalse(ready)
        self.assertFalse(plr)
        self.assertIn("A15", reason)

    def test_same_prospect_passing_a15_reaches_enterprise_ready(self):
        ready, _, route, _, proceed = _determine_review_route(
            **self.STRONG, a15_deliberate_decision="pass")
        self.assertEqual(route, "enterprise_ready")
        self.assertTrue(ready)
        self.assertTrue(proceed)

    def test_unknown_a15_does_not_gate(self):
        _, _, route, _, proceed = _determine_review_route(
            **self.STRONG, a15_deliberate_decision="unknown")
        self.assertEqual(route, "enterprise_ready")
        self.assertTrue(proceed)

    def test_a15_failure_blocks_the_product_led_route_too(self):
        _, _, route, reason, proceed = _determine_review_route(
            product_led_user_fit=95, enterprise_company_fit=10, purchase_readiness=0,
            a15_deliberate_decision="fail")
        self.assertEqual(route, "hold")
        self.assertFalse(proceed)
        self.assertIn("A15", reason)

    def test_thresholds_are_unchanged_when_a15_passes(self):
        _, _, route, _, _ = _determine_review_route(
            product_led_user_fit=60, enterprise_company_fit=10, purchase_readiness=0,
            a15_deliberate_decision="pass")
        self.assertEqual(route, "product_led_review")



class ReconciledReadinessRulesTests(unittest.TestCase):
    """R-codes now score the meaning the current brief gives them."""

    @staticmethod
    def _request():
        return QualificationRequest.model_validate({
            "prospect": {"id": "p1", "name": "T", "job_title": "COO", "company": "C"},
            "evidence": [{"id": "e1", "claim": "signals", "confidence": 90}],
        })

    @staticmethod
    def _sigs(codes, signal_date="2026-09-01"):
        return [ReadinessSignalAssessment.model_validate({
            "signal_code": c, "evidence_id": "e1", "signal_date": signal_date,
            "signal_date_precision": "day", "rationale": "x"}) for c in codes]

    AS_OF = date(2026, 9, 1)

    def test_r11_is_rejected_by_the_schema(self):
        with self.assertRaises(Exception):
            ReadinessSignalAssessment.model_validate({
                "signal_code": "R11", "evidence_id": "e1", "signal_date": "2026-09-01",
                "signal_date_precision": "day", "rationale": "retired code"})

    def test_cap_applies_when_no_named_strategic_decision(self):
        # R3+R4+R5+R6+R7 = 45 raw, but no R2 means the cap binds at 40.
        score = _calculate_purchase_readiness(
            self._request(), self._sigs(["R3", "R4", "R5", "R6", "R7"]), as_of=self.AS_OF)
        self.assertEqual(score, 40)

    def test_named_strategic_decision_lifts_the_cap(self):
        # R2 is now the gate, so a cold prospect can clear the 45 enterprise threshold.
        score = _calculate_purchase_readiness(
            self._request(), self._sigs(["R2", "R3", "R4"]), as_of=self.AS_OF)
        self.assertEqual(score, 47)
        self.assertGreaterEqual(score, 45)

    def test_existing_usage_floors_a_decayed_score(self):
        # R1 alone, three years stale, still floors at 35 - usage compounds.
        score = _calculate_purchase_readiness(
            self._request(), self._sigs(["R1"], "2023-09-01"), as_of=self.AS_OF)
        self.assertEqual(score, 35)

    def test_board_pressure_no_longer_floors(self):
        # The floor used to sit on R8; R8 now means board/PE pressure and must not floor.
        score = _calculate_purchase_readiness(
            self._request(), self._sigs(["R8"], "2023-09-01"), as_of=self.AS_OF)
        self.assertLess(score, 35)

    def test_reconciled_points_and_windows(self):
        self.assertEqual(READINESS_RULES["R1"], (15, 365))
        self.assertEqual(READINESS_RULES["R2"], (25, 45))
        self.assertEqual(READINESS_RULES["R3"], (12, 90))
        self.assertEqual(READINESS_RULES["R8"], (8, 180))
        self.assertEqual(READINESS_RULES["R9"], (7, 21))
        self.assertEqual(READINESS_RULES["R10"], (8, 21))
        self.assertNotIn("R11", READINESS_RULES)


if __name__ == "__main__":
    unittest.main()
