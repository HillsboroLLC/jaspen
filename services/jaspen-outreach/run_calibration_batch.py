from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import httpx

from app import Evidence, Prospect, QualificationRequest, qualify_with_openai


def build_request(account: dict) -> QualificationRequest:
    index = int(account["index"])
    prospect_name = f"CAL-{index:02d} - {account['company']}"
    evidence = [
        Evidence(
            id=item["source_key"],
            claim=item["claim"],
            evidence_type=item.get("type"),
            source_title=item.get("source_title"),
            source_url=item.get("source_url"),
            observed_at=item.get("observed_date"),
            confidence=item.get("confidence"),
        )
        for item in account["evidence"]
    ]
    return QualificationRequest(
        prospect=Prospect(
            id=account["account_id"],
            name=prospect_name,
            job_title="Founder-review calibration account",
            company=account["company"],
            domain=account.get("domain"),
            research_summary=account["prospect"].get("research_summary"),
        ),
        evidence=evidence,
    )


async def qualify_account(account: dict, semaphore: asyncio.Semaphore) -> dict:
    response = None
    for attempt in range(3):
        try:
            async with semaphore:
                response = await qualify_with_openai(build_request(account))
            break
        except (httpx.TimeoutException, ValueError):
            if attempt == 2:
                raise
            await asyncio.sleep(2 ** attempt)
    assert response is not None
    return {
        "index": account["index"],
        "account_id": account["account_id"],
        "company": account["company"],
        "baseline_company_fit": account["baseline_company_fit"],
        "baseline_purchase_readiness": account["baseline_purchase_readiness"],
        "qualification": response.model_dump(mode="json"),
    }


async def run_batch(source: Path, destination: Path, concurrency: int) -> None:
    accounts = json.loads(source.read_text())
    semaphore = asyncio.Semaphore(concurrency)
    results = await asyncio.gather(
        *(qualify_account(account, semaphore) for account in accounts)
    )
    results.sort(key=lambda item: item["index"])
    temp_path = destination.with_suffix(destination.suffix + ".tmp")
    temp_path.write_text(json.dumps(results, indent=2) + "\n")
    temp_path.replace(destination)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args()
    asyncio.run(run_batch(args.source, args.destination, args.concurrency))


if __name__ == "__main__":
    main()
