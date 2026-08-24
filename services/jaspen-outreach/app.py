from __future__ import annotations

import hashlib
import hmac
import os

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException

from packages.outreach.qualify.qualification_core import (
    DEFAULT_MODEL,
    PROMPT_VERSION,
    RUBRIC_VERSION,
    Evidence,
    Prospect,
    QualificationModelOutput,
    QualificationRequest,
    QualificationResponse,
    build_openai_payload as _build_openai_payload,
    qualify_with_openai,
    validate_traceability as _validate_traceability,
)


def require_shared_secret(
    x_jaspen_outreach_secret: str = Header(default=""),
) -> None:
    expected = os.environ.get("JASPEN_OUTREACH_SHARED_SECRET", "")
    if not expected or not hmac.compare_digest(x_jaspen_outreach_secret, expected):
        raise HTTPException(status_code=401, detail="Unauthorized")


app = FastAPI(title="Jaspen Outreach Intelligence", version="1.0.0")


@app.get("/health")
async def health() -> dict[str, str]:
    model = os.environ.get("OPENAI_MODEL", DEFAULT_MODEL)
    return {
        "status": "ok",
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "rubric_version": RUBRIC_VERSION,
    }


@app.post(
    "/v1/qualify",
    response_model=QualificationResponse,
    dependencies=[Depends(require_shared_secret)],
)
async def qualify(request: QualificationRequest) -> QualificationResponse:
    try:
        return await qualify_with_openai(request)
    except httpx.HTTPStatusError as exc:
        request_id = exc.response.headers.get("x-request-id", "")
        safe_suffix = f" request_id={request_id}" if request_id else ""
        raise HTTPException(
            status_code=502,
            detail=f"OpenAI request failed with status {exc.response.status_code}.{safe_suffix}",
        ) from exc
    except (ValueError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def safe_prospect_fingerprint(prospect_id: str) -> str:
    return hashlib.sha256(prospect_id.encode("utf-8")).hexdigest()[:16]

