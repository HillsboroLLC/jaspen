from __future__ import annotations

import json
import math
import os
import re
from datetime import date, datetime, timezone
from typing import Literal, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator


PROMPT_VERSION = "qualification-v3.1"
RUBRIC_VERSION = "jaspen-rubric-v3.1"
DEFAULT_MODEL = "gpt-5-mini"
PRODUCT_LED_FIT_THRESHOLD = 60
ENTERPRISE_FIT_THRESHOLD = 55
PURCHASE_READINESS_THRESHOLD = 45

PRODUCT_LED_RATING_POINTS = {
    "unknown": 0,
    "absent": 0,
    "weak": 1,
    "moderate": 2,
    "strong": 3,
}

# Reconciled 2026-08-25 against Jaspen Sales Playbook & ICP Brief section 12-C.
# The previous table was inherited from the archived brief, whose R-codes carried
# different meanings; six codes were scoring the wrong signal. Points and decay
# windows are unchanged as a set - only the code each is attached to was corrected.
# (points, half_life_days): 21d act-within-days, 45d fast, 90d predictable,
# 180d medium, 365d slow and compounding.
READINESS_RULES = {
    "R1": (15, 365),   # Existing Jaspen usage - slow, persists and compounds
    "R2": (25, 45),    # Named strategic decision underway - fast
    "R3": (12, 90),    # Budget or planning cycle within 90 days - predictable
    "R4": (10, 180),   # New CTrO/CSO/COO or comparable leader in seat - medium
    "R5": (8, 180),    # M&A, restructuring, or integration - medium
    "R6": (8, 45),     # Cost reduction / budget cut - fast
    "R7": (7, 180),    # Acute capacity constraints - medium
    "R8": (8, 180),    # Board or PE pressure event - medium
    "R9": (7, 21),     # Expansion behavior - fast (provisional calibration)
    "R10": (8, 21),    # Advisory intent - fast (provisional calibration)
}


class Prospect(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=300)
    job_title: Optional[str] = Field(default=None, max_length=300)
    company: Optional[str] = Field(default=None, max_length=300)
    domain: Optional[str] = Field(default=None, max_length=300)
    research_summary: Optional[str] = Field(default=None, max_length=4000)


class Evidence(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    claim: str = Field(min_length=1, max_length=4000)
    evidence_type: Optional[str] = Field(default=None, max_length=200)
    source_title: Optional[str] = Field(default=None, max_length=500)
    source_url: Optional[str] = Field(default=None, max_length=2000)
    observed_at: Optional[datetime] = None
    confidence: Optional[int] = Field(default=None, ge=0, le=100)


class QualificationRequest(BaseModel):
    prospect: Prospect
    evidence: list[Evidence] = Field(min_length=1, max_length=50)

    @field_validator("evidence")
    @classmethod
    def evidence_ids_must_be_unique(cls, evidence: list[Evidence]) -> list[Evidence]:
        ids = [item.id for item in evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("Evidence IDs must be unique")
        return evidence


ProductLedRating = Literal["unknown", "absent", "weak", "moderate", "strong"]
ReadinessSignalCode = Literal[
    "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "R10"
]
SignalDatePrecision = Literal["day", "month", "quarter"]
ReviewRoute = Literal[
    "enterprise_ready", "product_led_review", "enterprise_nurture", "hold"
]


class ProductLedCriteria(BaseModel):
    model_config = ConfigDict(extra="forbid")

    p1_consequential_decision: ProductLedRating
    p2_human_judgment: ProductLedRating
    p3_accountability_defensibility: ProductLedRating
    p4_incomplete_mixed_evidence: ProductLedRating
    p5_real_tradeoffs: ProductLedRating
    p6_near_term_reason: ProductLedRating
    p7_direct_product_value: ProductLedRating
    p8_repeat_use_potential: ProductLedRating


class ReadinessSignalAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    signal_code: ReadinessSignalCode
    evidence_id: str = Field(min_length=1, max_length=100)
    signal_date: date
    signal_date_precision: SignalDatePrecision
    rationale: str = Field(min_length=1, max_length=1000)


class QualificationModelOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall_qualification: Literal["High", "Medium", "Low"]
    a15_deliberate_decision: Literal["pass", "fail", "unknown"]
    product_led_criteria: ProductLedCriteria
    enterprise_company_fit: int = Field(ge=0, le=100)
    readiness_signals: list[ReadinessSignalAssessment] = Field(max_length=11)
    evidence_coverage: int = Field(ge=0, le=100)
    evidence_confidence: int = Field(ge=0, le=100)
    recency: int = Field(ge=0, le=100)
    remit_connection: int = Field(ge=0, le=100)
    recommended_outreach_angle: str = Field(min_length=1, max_length=2000)
    qualification_rationale: str = Field(min_length=1, max_length=4000)
    used_evidence_ids: list[str] = Field(min_length=1, max_length=50)

    @field_validator("used_evidence_ids")
    @classmethod
    def used_ids_must_be_unique(cls, ids: list[str]) -> list[str]:
        if len(ids) != len(set(ids)):
            raise ValueError("Used evidence IDs must be unique")
        return ids


class QualificationResponse(QualificationModelOutput):
    product_led_user_fit: int = Field(ge=0, le=100)
    product_led_evidence_coverage: int = Field(ge=0, le=100)
    purchase_readiness: int = Field(ge=0, le=100)
    enterprise_ready: bool
    product_led_review_eligible: bool
    review_route: ReviewRoute
    route_reason: str
    proceed_to_outreach: bool
    prospect_id: str
    evidence_count: int
    model: str
    prompt_version: str
    rubric_version: str
    qualified_at: datetime


def qualification_schema() -> dict:
    schema = QualificationModelOutput.model_json_schema()
    schema["additionalProperties"] = False
    return schema


def extract_output_text(response_json: dict) -> str:
    for item in response_json.get("output", []):
        if item.get("type") != "message":
            continue
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"]
    raise ValueError("OpenAI response did not contain structured output text")


def validate_traceability(
    request: QualificationRequest, output: QualificationModelOutput
) -> list[ReadinessSignalAssessment]:
    supplied_ids = {item.id for item in request.evidence}
    used_ids = set(output.used_evidence_ids)
    unknown_ids = sorted(used_ids - supplied_ids)
    if unknown_ids:
        raise ValueError(
            "Model referenced evidence that was not supplied: " + ", ".join(unknown_ids)
        )

    supplied_by_id = {item.id: item for item in request.evidence}
    seen_signals: set[tuple[str, str]] = set()
    valid_signals: list[ReadinessSignalAssessment] = []
    for signal in output.readiness_signals:
        if signal.evidence_id not in supplied_ids:
            raise ValueError("Readiness signal referenced evidence that was not supplied")
        if signal.evidence_id not in used_ids:
            continue
        key = (signal.signal_code, signal.evidence_id)
        if key in seen_signals:
            continue
        seen_signals.add(key)
        evidence = supplied_by_id[signal.evidence_id]
        if not re.search(rf"\b{signal.signal_code}\b", evidence.claim, re.IGNORECASE):
            continue
        if not _evidence_supports_signal_date(evidence, signal):
            continue
        valid_signals.append(signal)
    return valid_signals


def _claim_bears_signal_date(
    claim: str, signal_date: date, precision: SignalDatePrecision
) -> bool:
    """True when the claim carries the signal date at the precision claimed.

    Each precision is checked against exactly what it asserts. A day-precision
    signal must find the day in the claim: matching only the month would let
    "April 2026" license a fabricated 2026-04-17.
    """
    claim = claim.lower()
    if str(signal_date.year) not in claim:
        return False

    quarter = f"q{((signal_date.month - 1) // 3) + 1} {signal_date.year}"
    if precision == "quarter":
        return quarter in claim

    month_names = {
        signal_date.strftime("%B").lower(),
        signal_date.strftime("%b").lower(),
    }
    month_present = (
        any(name in claim for name in month_names)
        or f"{signal_date.year}-{signal_date.month:02d}" in claim
        or f"{signal_date.month}/{signal_date.year}" in claim
    )
    if precision == "month":
        return month_present

    day = signal_date.day
    day_tokens = {
        signal_date.isoformat(),
        f"{signal_date.month}/{day}/{signal_date.year}",
        f"{signal_date.strftime('%B').lower()} {day}",
        f"{signal_date.strftime('%b').lower()} {day}",
        f"{day} {signal_date.strftime('%B').lower()}",
    }
    return month_present and any(token in claim for token in day_tokens)


def _decay_anchor(signal_date: date, precision: SignalDatePrecision) -> date:
    """Earliest date consistent with the stated precision.

    Conservative by construction: the earliest plausible date maximises elapsed
    time and therefore decay, so imprecision costs readiness rather than earning
    it. The anchor is never presented as a sourced date - see _format_signal_date.
    """
    if precision == "day":
        return signal_date
    if precision == "month":
        return signal_date.replace(day=1)
    first_month_of_quarter = ((signal_date.month - 1) // 3) * 3 + 1
    return signal_date.replace(month=first_month_of_quarter, day=1)


def _format_signal_date(signal: "ReadinessSignalAssessment") -> str:
    """Render a signal date at the precision the source actually supplied."""
    if signal.signal_date_precision == "day":
        return signal.signal_date.isoformat()
    if signal.signal_date_precision == "month":
        return f"{signal.signal_date.year}-{signal.signal_date.month:02d} (month precision)"
    quarter = ((signal.signal_date.month - 1) // 3) + 1
    return f"Q{quarter} {signal.signal_date.year} (quarter precision)"


def _evidence_supports_signal_date(
    evidence: Evidence, signal: "ReadinessSignalAssessment"
) -> bool:
    """A readiness date must appear in the evidence claim itself.

    observed_at deliberately plays no part. It records when the evidence was
    observed, not when the event occurred, so it cannot attest an event date - and
    a model with no date to work from will simply echo observed_at back, turning
    "took office last spring" into a signal dated today. Requiring the date in the
    claim text is the only check the model cannot satisfy by restating our own input.
    """
    return _claim_bears_signal_date(
        evidence.claim, signal.signal_date, signal.signal_date_precision
    )


def calculate_product_led_fit(criteria: ProductLedCriteria) -> tuple[int, int]:
    ratings = list(criteria.model_dump().values())
    points = sum(PRODUCT_LED_RATING_POINTS[rating] for rating in ratings)
    observed = sum(rating != "unknown" for rating in ratings)
    score = round(points / (3 * len(ratings)) * 100)
    coverage = round(observed / len(ratings) * 100)
    return score, coverage


def _confidence_multiplier(confidence: Optional[int]) -> float:
    if confidence is None or confidence < 50:
        return 0.4
    if confidence < 80:
        return 0.7
    return 1.0


def calculate_purchase_readiness(
    request: QualificationRequest,
    signals: list[ReadinessSignalAssessment],
    *,
    as_of: date,
) -> int:
    evidence_by_id = {item.id: item for item in request.evidence}
    total = 0.0
    present_codes: set[str] = set()
    for signal in signals:
        base_points, half_life_days = READINESS_RULES[signal.signal_code]
        anchor = _decay_anchor(signal.signal_date, signal.signal_date_precision)
        days_since = max(0, (as_of - anchor).days)
        decay = math.pow(0.5, days_since / half_life_days)
        confidence = _confidence_multiplier(evidence_by_id[signal.evidence_id].confidence)
        total += base_points * decay * confidence
        present_codes.add(signal.signal_code)
    score = min(100, round(total))
    # Both rules were written against the archived numbering and have been
    # re-pointed to the codes that now carry their meaning. Values unchanged.
    # Cap: without a nameable strategic decision (now R2) there is nurture, not pursuit.
    if "R2" not in present_codes:
        score = min(score, 40)
    # Floor: existing Jaspen usage (now R1) alone justifies working an account.
    if "R1" in present_codes:
        score = max(score, 35)
    return score


def reconcile_qualification_rationale(
    rationale: str,
    signals: list[ReadinessSignalAssessment],
    *,
    purchase_readiness: int,
) -> str:
    """Replace model-authored readiness prose with guardrail-approved facts."""
    sentences = re.split(r"(?<=[.!?])\s+|[\r\n]+", rationale.strip())
    readiness_reference = re.compile(
        r"\b(?:purchase\s+readiness|readiness(?:\s+signal)?|R(?:1[01]|[1-9]))\b",
        re.IGNORECASE,
    )
    retained = " ".join(
        sentence.strip()
        for sentence in sentences
        if sentence.strip() and not readiness_reference.search(sentence)
    )

    if signals:
        accepted = ", ".join(
            f"{signal.signal_code} (evidence {signal.evidence_id}, dated {_format_signal_date(signal)})"
            for signal in signals
        )
        canonical = (
            f"Guardrail-validated Purchase Readiness signals: {accepted}. "
            f"Purchase Readiness is {purchase_readiness}/100 and is calculated only from these accepted signals."
        )
    else:
        canonical = (
            "No explicit dated R1-R11 Purchase Readiness signal survived guardrail validation; "
            "Purchase Readiness is 0/100."
        )

    separator = " " if retained else ""
    retained_budget = max(0, 4000 - len(separator) - len(canonical))
    if len(retained) > retained_budget:
        retained = retained[:retained_budget].rstrip()
        separator = " " if retained else ""
    return f"{retained}{separator}{canonical}"


def determine_review_route(
    *,
    product_led_user_fit: int,
    enterprise_company_fit: int,
    purchase_readiness: int,
    a15_deliberate_decision: Literal["pass", "fail", "unknown"],
) -> tuple[bool, bool, ReviewRoute, str, bool]:
    # A15 is a hard gate in the ICP brief ("hard disqualifier when it fails"),
    # so it is evaluated before any threshold. "unknown" does not gate: absent
    # evidence is not a failed test.
    if a15_deliberate_decision == "fail":
        return (
            False,
            False,
            "hold",
            "A15 gate: the decision domain is algorithmic or high-volume, which the "
            "ICP brief treats as a hard disqualifier. Fit and readiness thresholds "
            "were not evaluated.",
            False,
        )
    enterprise_ready = (
        enterprise_company_fit >= ENTERPRISE_FIT_THRESHOLD
        and purchase_readiness >= PURCHASE_READINESS_THRESHOLD
    )
    product_led_eligible = product_led_user_fit >= PRODUCT_LED_FIT_THRESHOLD
    if enterprise_ready:
        route: ReviewRoute = "enterprise_ready"
        reason = "Enterprise Company Fit and explicit dated Purchase Readiness meet 55/45."
    elif product_led_eligible:
        route = "product_led_review"
        reason = "Normalized Product-Led User Fit meets 60; enterprise thresholds are not required for self-serve review."
    elif enterprise_company_fit >= ENTERPRISE_FIT_THRESHOLD:
        route = "enterprise_nurture"
        reason = "Enterprise Company Fit meets 55, but explicit dated Purchase Readiness is below 45."
    else:
        route = "hold"
        reason = "Neither the product-led review threshold nor the enterprise-ready conditions are met."
    proceed = route in {"enterprise_ready", "product_led_review"}
    return enterprise_ready, product_led_eligible, route, reason, proceed


def build_openai_payload(request: QualificationRequest, model: str) -> dict:
    evidence_json = [item.model_dump(mode="json") for item in request.evidence]
    input_payload = {
        "prospect": request.prospect.model_dump(mode="json"),
        "evidence": evidence_json,
    }
    return {
        "model": model,
        "store": False,
        "max_output_tokens": 4000,
        "instructions": (
            "For every readiness signal you must also return signal_date_precision, stating the "
            "precision the SOURCE actually supplied: 'day' only when the evidence gives a "
            "specific day, 'month' when it gives only a month and year, 'quarter' when it "
            "gives only a quarter. Never invent a day to satisfy the field. "
            "You must also return a15_deliberate_decision: 'fail' when the decision domain is "
            "algorithmic, high-volume or real-time (pricing engines, credit decisioning, ad "
            "bidding, supply-chain optimisation, payments optimisation); 'pass' when the "
            "decision is deliberate, human-owned, low-frequency and high-stakes; 'unknown' "
            "when the supplied evidence does not establish which it is. "
            "You qualify Jaspen outreach prospects for founder review. Use only the Evidence "
            "objects supplied in the input for factual judgments. Prospect fields provide identity "
            "and context but are not evidence of readiness or fit. Never invent, browse for, or cite "
            "facts outside the supplied Evidence objects. Preserve three independent dimensions. "
            "For Product-Led User Fit, rate every P1-P8 criterion as unknown, absent, weak, moderate, "
            "or strong. P1 consequential decision; P2 human judgment; P3 accountability/defensibility; "
            "P4 incomplete or mixed evidence; P5 real trade-offs; P6 near-term reason to act; P7 direct "
            "product value without consulting; P8 repeat-use potential. Use unknown when the evidence "
            "does not permit a judgment and absent only for an evidenced absence. Title alone is not "
            "evidence of decision need. The service, not the model, converts P1-P8 into a normalized "
            "0-100 score. enterprise_company_fit measures structural company "
            "fit using the A1-A15 method, with A1-A5 carrying the core weight and desk research unable "
            "to justify Tier A without discovery validation. For Purchase Readiness, return only explicit "
            "R1-R11 signals whose R-code and date are stated in the same supplied Evidence claim. Do not "
            "infer readiness from title, role scope, seniority, generic strategic relevance, an undated "
            "job posting, or company fit. For each accepted signal return its exact evidence_id, R-code, "
            "ISO signal_date, and rationale. The service validates and scores these signals using the "
            "existing base points, confidence multipliers, decay, R1 cap, and R8 floor. Never average "
            "the three dimensions. "
            "Missing evidence is unknown, not zero. evidence_coverage measures how much of the relevant "
            "rubric can be judged from supplied evidence; low coverage must be stated as uncertainty, "
            "not false precision. Every rationale and angle must be supported by used_evidence_ids, "
            "and every used ID must exactly match an input Evidence.id. Overall Qualification is informational "
            "only and must not be used to route. Do not choose a route or a proceed flag; the service applies "
            f"the frozen enterprise thresholds ({ENTERPRISE_FIT_THRESHOLD}/{PURCHASE_READINESS_THRESHOLD}) "
            f"and the provisional product-led review threshold ({PRODUCT_LED_FIT_THRESHOLD}). Every route is "
            "review-only and does not authorize drafting or sending. If evidence is weak, stale, "
            "unrelated, conflicting, or insufficient, lower confidence/coverage and explain why. Return the "
            "requested structured output."
        ),
        "input": json.dumps(input_payload, separators=(",", ":")),
        "text": {
            "format": {
                "type": "json_schema",
                "name": "jaspen_lead_qualification",
                "strict": True,
                "schema": qualification_schema(),
            }
        },
    }


async def qualify_with_openai(
    request: QualificationRequest,
    *,
    client: Optional[httpx.AsyncClient] = None,
) -> QualificationResponse:
    api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
    payload = build_openai_payload(request, model)
    owns_client = client is None
    if client is None:
        client = httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0))

    try:
        response = await client.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {api_key}"},
            json=payload,
        )
        response.raise_for_status()
        raw_output = extract_output_text(response.json())
        parsed = QualificationModelOutput.model_validate_json(raw_output)
        valid_readiness_signals = validate_traceability(request, parsed)
        parsed = parsed.model_copy(
            update={"readiness_signals": valid_readiness_signals}
        )
        qualified_at = datetime.now(timezone.utc)
        product_led_user_fit, product_led_evidence_coverage = (
            calculate_product_led_fit(parsed.product_led_criteria)
        )
        purchase_readiness = calculate_purchase_readiness(
            request, parsed.readiness_signals, as_of=qualified_at.date()
        )
        parsed = parsed.model_copy(
            update={
                "qualification_rationale": reconcile_qualification_rationale(
                    parsed.qualification_rationale,
                    parsed.readiness_signals,
                    purchase_readiness=purchase_readiness,
                )
            }
        )
        (
            enterprise_ready,
            product_led_review_eligible,
            review_route,
            route_reason,
            proceed_to_outreach,
        ) = determine_review_route(
            product_led_user_fit=product_led_user_fit,
            enterprise_company_fit=parsed.enterprise_company_fit,
            purchase_readiness=purchase_readiness,
            a15_deliberate_decision=parsed.a15_deliberate_decision,
        )
        return QualificationResponse(
            **parsed.model_dump(),
            product_led_user_fit=product_led_user_fit,
            product_led_evidence_coverage=product_led_evidence_coverage,
            purchase_readiness=purchase_readiness,
            enterprise_ready=enterprise_ready,
            product_led_review_eligible=product_led_review_eligible,
            review_route=review_route,
            route_reason=route_reason,
            proceed_to_outreach=proceed_to_outreach,
            prospect_id=request.prospect.id,
            evidence_count=len(request.evidence),
            model=model,
            prompt_version=PROMPT_VERSION,
            rubric_version=RUBRIC_VERSION,
            qualified_at=qualified_at,
        )
    finally:
        if owns_client:
            await client.aclose()
