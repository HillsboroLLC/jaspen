# Codex brief — lead capture endpoint for the Decision Scorecard magnet

Status: PROPOSED. Not yet implemented. Frontend is already wired and waiting.
Author: marketing pass (Claude). For Fable to review, advise, and implement.

## Why this exists

The homepage now has a lead magnet: a free "Decision Scorecard" spreadsheet
(`frontend/public/Jaspen-Decision-Scorecard.xlsx`). The capture form lives in
`frontend/src/homeSections/HomePage/LeadCapture.jsx`.

Right now the form does two things on submit:
1. Immediately downloads the spreadsheet (this is the user value, always works).
2. Makes a **best-effort** `POST` to `${API_BASE}/api/v1/public/leads` that is
   wrapped in `try/catch` and is safe to fail. Nothing stores the email yet.

This brief describes the small backend endpoint that closes that gap so we
actually capture the lead. It was intentionally left unbuilt because the
current marketing pass was scoped to frontend-only (no backend source edits).

## The contract the frontend already sends

`LeadCapture.jsx` posts JSON:

```json
{ "email": "you@company.com", "source": "decision-scorecard" }
```

- Method: `POST`
- URL: `/api/v1/public/leads`
- No auth header (this is a public, pre-signup endpoint).
- The frontend ignores the response body and never blocks on it. A 200 or a
  network error both leave the UX identical (download proceeds). So the
  endpoint can evolve freely without a frontend change.

## Suggested implementation (mirrors existing patterns)

### 1. Model — `app/models.py`

Add a `Lead` model in the same style as the other models (UUID string PK,
`datetime.utcnow` timestamps):

```python
class Lead(db.Model):
    __tablename__ = 'leads'
    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    email = db.Column(db.String(255), nullable=False, index=True)
    source = db.Column(db.String(80), nullable=True)     # e.g. "decision-scorecard"
    first_name = db.Column(db.String(120), nullable=True)  # reserved for future
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
```

Dedupe policy is a judgment call for Fable: either a unique index on `email`
with an upsert, or allow repeats and de-dupe at export time. Repeats are
simpler and lose nothing.

### 2. Table creation — no new Alembic migration

The migration history currently has **six heads** (confirmed:
`6b8c1d2e3f4a`, `c7d1d8a9f2be`, `9a6f2c4b8d1e`, `d83909756dd2`, `3c5f9a2b7e10`,
`d4e5f6a7b8c9`), which is why the repo uses `db.create_all()` in
`scripts/init_dev_db.py` rather than `flask db upgrade`. For **localhost**,
running `scripts/init_dev_db.py` will create the `leads` table with zero risk
(`create_all` only creates missing tables).

For **production**, do NOT add a seventh head casually. Recommend Fable first
decides whether to merge the existing heads, then adds one migration for
`leads` on top of the merged head. This is the main thing to get right and the
reason this was left for review rather than auto-implemented.

### 3. Route — new `app/routes/leads.py`

Mirror `app/routes/public_intake.py` (public blueprint, rate limited):

```python
from flask import Blueprint, jsonify, request
from app import db, limiter
from app.models import Lead

leads_bp = Blueprint("leads", __name__)
EMAIL_RE = ...  # basic RFC-ish check

@leads_bp.route("/leads", methods=["POST"])
@limiter.limit("5 per minute")
@limiter.limit("30 per hour")
def capture_lead():
    data = request.get_json(silent=True) or {}
    email = str(data.get("email", "")).strip().lower()
    source = str(data.get("source", "")).strip()[:80] or None
    if not EMAIL_RE.match(email):
        return jsonify({"error": "invalid_email"}), 400
    db.session.add(Lead(email=email, source=source))
    db.session.commit()
    # Optional: deliver the file by email here (see section 4).
    return jsonify({"ok": True}), 200
```

Register in `app/__init__.py` next to the other public blueprint:

```python
from .routes.leads import leads_bp
app.register_blueprint(leads_bp, url_prefix='/api/v1/public')
```

That yields the exact path the frontend already calls: `/api/v1/public/leads`.

### 4. Email delivery (optional, reuses existing flask-mail)

The app already sends mail (`flask_mail`, used in `app/routes/auth.py` for
verification and password reset). A delivery email can reuse that pattern with
a `Message(...)` + `mail.send(msg)`. Simplest and most reliable across the
split frontend/backend deploys: email a **link** to the public asset
(`https://jaspen.ai/Jaspen-Decision-Scorecard.xlsx`) rather than attaching the
file. Sending mail should be best-effort and must not fail the request if SMTP
is unavailable (wrap in try/except, log, still return 200).

Note: local dev needs `MAIL_*` env vars set for real sends; otherwise skip the
email locally and just confirm the row lands in `leads`.

## Security and abuse notes

- Rate limit per the example (the limiter is already app-wide).
- Validate and lowercase the email; cap `source` length.
- No secrets, no auth, no PII beyond the email the user typed.
- Consider a honeypot field or hCaptcha later if spam appears. Not needed for launch.

## How to verify

1. Run `scripts/init_dev_db.py` locally; confirm `leads` appears in "Tables created".
2. Submit the homepage form; confirm a row lands in `leads` and the download still works.
3. Bad email returns 400; the frontend still downloads (it ignores the response).
4. If email delivery is enabled, confirm a link email arrives and a dead SMTP
   does not 500 the endpoint.

## Explicitly out of scope / do not change

- Do not edit `.env`, CI workflows, or deploy config.
- Do not wire this to a third-party ESP unless that decision is revisited.
- No frontend change is required; `LeadCapture.jsx` already targets this path.
