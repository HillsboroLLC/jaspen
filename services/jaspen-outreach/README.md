# Jaspen Outreach Intelligence

Small server-side intelligence boundary for the Dataverse outreach MVP.

The qualification endpoint accepts one prospect plus Evidence Item records, calls the OpenAI Responses API with a strict JSON schema, and rejects any model output that references evidence IDs outside the supplied Dataverse set. Qualification v3 preserves Product-Led User Fit, Enterprise Company Fit, and Purchase Readiness as separate dimensions, alongside Evidence Coverage and a fixed Rubric Version.

The service deterministically normalizes Product-Led User Fit from explicit P1-P8 ratings and calculates Purchase Readiness only from explicit, dated R1-R11 evidence using the existing point, confidence, and decay rules. The model cannot choose the route. The provisional enterprise thresholds remain frozen at 55 Company Fit / 45 Purchase Readiness, while a separate provisional 60+ Product-Led User Fit route sends a record to founder review. Overall Qualification is informational only. Every route is review-only; the endpoint never drafts or sends outreach.

## Environment

- `OPENAI_API_KEY` — existing OpenAI project secret.
- `OPENAI_MODEL` — optional; defaults to `gpt-5-mini`.
- `JASPEN_OUTREACH_SHARED_SECRET` — required request authentication for `/v1/qualify`.

## Run

```bash
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app:app --host 127.0.0.1 --port 8091
```

`GET /health` is intentionally non-secret-bearing. `POST /v1/qualify` requires the `X-Jaspen-Outreach-Secret` header.

## Deploy

The permanent qualification endpoint is a DigitalOcean Function in the
`jaspen-outreach` namespace (`fn-80c02947-9ce2-4fe1-9da4-658c2bc0bbcc`). It has no
shell — it is updated only by uploading a new version with `doctl`.

```bash
./deploy.sh --check   # validate credentials and deploy target, change nothing
./deploy.sh           # validate, then deploy
```

`deploy.sh` always passes `--remote-build`. This is required, not a preference:
`requirements.txt` pins `pydantic`, whose `pydantic-core` dependency ships
platform-specific compiled wheels. Building on macOS produces darwin binaries that
cannot run on the `python:3.12` Linux runtime, and `build.sh` additionally assumes
`virtualenv` plus a hardcoded `python3.12` site-packages path. `--remote-build`
makes DigitalOcean build on a machine matching the runtime.

Credentials load only from `~/.jaspen-outreach-deploy.env` (mode `600`, never
committed). The script verifies every required variable is present and reports only
character counts, never values. Required:

- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `JASPEN_OUTREACH_SHARED_SECRET` — must match the header Power Automate sends
- `JASPEN_FUNCTION_WEB_SECRET` — the DO platform `webSecure` gate
- `DIGITALOCEAN_ACCESS_TOKEN`

The two secrets are shared with the `Jaspen - Qualify Prospect` Power Automate flow.
Changing either without updating the flow breaks every run, so they must be rotated
in lockstep.

### Rollback

The FastAPI service in this directory is the rollback path and is not in the
qualification request path. To roll the Function back, redeploy a prior digest
recorded in `.deployed/versions.json` (untracked, written by `doctl` at deploy time).
