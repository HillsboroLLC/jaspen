import asyncio
import json

import httpx

from app import QualificationRequest, qualify_with_openai


async def main() -> None:
    request = QualificationRequest.model_validate(
        {
            "prospect": {
                "id": "controlled-test-prospect",
                "name": "Controlled MVP Test Prospect",
                "job_title": "Operations Leader",
                "company": "Controlled Test Company",
            },
            "evidence": [
                {
                    "id": "controlled-evidence-1",
                    "claim": "This is controlled test evidence supplied solely to validate the qualification service.",
                    "evidence_type": "Controlled Test",
                    "source_title": "Jaspen Outreach MVP controlled test",
                    "source_url": "https://jaspen.ai",
                    "confidence": 100,
                }
            ],
        }
    )
    result = await qualify_with_openai(request)
    print(
        json.dumps(
            {
                "status": "ok",
                "overall_qualification": result.overall_qualification,
                "proceed_to_outreach": result.proceed_to_outreach,
                "used_evidence_ids": result.used_evidence_ids,
                "model": result.model,
                "prompt_version": result.prompt_version,
            }
        )
    )


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except httpx.HTTPStatusError as exc:
        error = exc.response.json().get("error", {})
        print(
            json.dumps(
                {
                    "status": "openai_error",
                    "http_status": exc.response.status_code,
                    "type": error.get("type"),
                    "code": error.get("code"),
                    "message": error.get("message"),
                    "request_id": exc.response.headers.get("x-request-id"),
                }
            )
        )
        raise SystemExit(1)
