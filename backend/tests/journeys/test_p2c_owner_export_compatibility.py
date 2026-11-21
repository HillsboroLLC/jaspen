"""H-2c acceptance: the owner's distribution outputs are byte-identical to P2b.

The same fixture project and the same owner requests are replayed and
compared with ``fixtures/p2c_owner_baseline_p2b.json``, recorded on the
accepted P2b commit (88ee9699) with this file. Each entry is a SHA-256 of the
response body plus its status, content type and download name.

Only values produced by the run itself are removed before hashing, each by
name: date-times within a day of now (session timestamps written by the
fixture's saves, the export time); the plan workbook's "Generated" cell;
Office core-properties ``created``/``modified``; PDF structure that encodes
byte offsets and lengths (xref, startxref, /Length) and the document /ID
(ReportLab's invariant mode fixes the PDF dates); and the random member and
organization ids (names are fixed before any request). Every other date or
number, including any stored in the project, is compared as is.

Re-record the baseline (only on P2b, never on P2c):
    P2C_WRITE_OWNER_BASELINE=1 pytest tests/journeys/test_p2c_owner_export_compatibility.py
"""

import hashlib
import io
import json
import os
import re
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app import db as _db
from tests.journeys.test_p2b_workspace_project_access import (  # noqa: F401 (fixtures)
    _call,
    _no_rate_limits,
    solo,
    team,
)
from tests.journeys.test_p2c_distribution_project_access import (  # noqa: F401 (fixtures)
    EXPORT_ROUTES,
    dist,
    report_calls,
    sent_emails,
)

BASELINE = Path(__file__).parent / "fixtures" / "p2c_owner_baseline_p2b.json"
_ISO = re.compile(rb"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?")


@pytest.fixture
def fixed_identities(dist, monkeypatch):
    """Fixed names for this run's members and organization, and ReportLab's
    invariant mode, so the bytes depend only on the project."""
    from reportlab import rl_config
    monkeypatch.setattr(rl_config, "invariant", 1)
    owner = dist["users"]["owner"]
    owner.name = "Owner Fixed"
    dist["org"].name = "Fixed Organization"
    _db.session.commit()
    return dist


def _normalize(team, data):
    for name, user in team["users"].items():
        data = data.replace(str(user.id).encode(), f"<user:{name}>".encode())
        data = data.replace(str(user.email).encode(), f"<email:{name}>".encode())
    data = data.replace(str(team["org"].id).encode(), b"<org>")
    # Only times produced during the run (within a day of now); dates stored
    # in the project are business data and are compared as they are.
    return _ISO.sub(_run_time, data)


def _run_time(match):
    raw = match.group(0).decode()
    try:
        stamp = datetime.fromisoformat(raw.replace("Z", "+00:00").replace(" ", "T")).replace(tzinfo=None)
    except ValueError:
        return match.group(0)
    if abs(stamp - datetime.utcnow()) <= timedelta(days=1):
        return b"<time>"
    return match.group(0)


# The plan workbook's "Generated" cell holds the export time as an Excel
# serial number; only that cell's value is masked.
_GENERATED_CELL = re.compile(
    rb"(<t>Generated</t></is></c><c r=\"B\d+\"[^>]*><v>)[0-9.]+(</v>)"
)


def _body_digest(team, response):
    data = response.data
    if data[:2] == b"PK":
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            parts = []
            for name in sorted(archive.namelist()):
                body = archive.read(name)
                if name == "docProps/core.xml":
                    body = re.sub(rb"<dcterms:(created|modified)[^>]*>[^<]*</dcterms:\1>", b"", body)
                parts.append(name.encode() + b"\0" + _normalize(team, body))
            data = b"\0\0".join(parts)
        data = _GENERATED_CELL.sub(rb"\1<serial-time>\2", data)
    elif data[:5] == b"%PDF-":
        data = _pdf_content(team, data)
    else:
        data = _normalize(team, data)
    return hashlib.sha256(data).hexdigest()


def _pdf_content(team, data):
    """The PDF with each compressed stream replaced by its normalized
    content, so a run-time timestamp inside page text does not count, while
    every other byte of every page still does."""
    import base64
    import zlib

    def _stream(match):
        raw = match.group(2)
        try:
            body = zlib.decompress(raw)
        except zlib.error:
            try:
                text = raw.strip()
                if text.endswith(b"~>"):
                    text = text[:-2]
                body = zlib.decompress(base64.a85decode(text, adobe=False))
            except Exception:
                body = raw
        return match.group(1) + _normalize(team, body) + b"\nendstream"

    data = re.sub(rb"(stream\r?\n)(.*?)\r?\n?endstream", _stream, data, flags=re.S)
    data = re.sub(rb"/Length \d+", b"/Length <n>", data)
    data = re.sub(rb"/ID\s*\[[^\]]*\]", b"/ID []", data)
    data = re.sub(rb"startxref\s+\d+", b"startxref <n>", data)
    data = re.sub(rb"\d{10} \d{5} [nf]", b"<xref>", data)
    return _normalize(team, data)


def _record(team, response):
    return {
        "status": response.status_code,
        "content_type": response.headers.get("Content-Type"),
        "disposition": response.headers.get("Content-Disposition"),
        "sha256": _body_digest(team, response),
    }


def _owner_outputs(client, team):
    card_id = team["projects"]["owner"][1]
    out = {}
    for route, template in sorted(EXPORT_ROUTES.items()):
        response = _call(client, team, "owner", "GET", template.format(t="t-shared", c=card_id))
        out[f"export/{route}"] = _record(team, response)
        # The same export without a scorecard id picks the project's card.
        if "{c}" in template:
            bare = template.split("?")[0].format(t="t-shared")
            out[f"export/{route}/default-card"] = _record(team, _call(client, team, "owner", "GET", bare))
    for route in ("scorecard-pdf", "wbs-csv"):
        missing = EXPORT_ROUTES[route].format(t="t-shared", c="no-such-card")
        out[f"export/{route}/unknown-card"] = {
            "status": _call(client, team, "owner", "GET", missing).status_code,
        }
    preview = _call(client, team, "owner", "POST", "/api/v1/shares/preview",
                    {"artifact_type": "scorecard", "thread_id": "t-shared", "scorecard_id": card_id})
    out["share/preview"] = _record(team, preview)
    starter = _call(client, team, "owner", "POST", "/api/v1/starters",
                    {"thread_id": "t-shared", "name": "Owner starter"})
    body = starter.get_json()["starter"]
    out["starter/create"] = {
        "status": starter.status_code,
        "fields": {key: body[key] for key in (
            "name", "objective", "lever_defaults", "scoring_weights", "intake_context",
            "is_shared", "source_thread_id",
        )},
    }
    return out


def test_owner_outputs_are_byte_identical_to_p2b(client, fixed_identities, report_calls, sent_emails):
    team = fixed_identities
    current = _owner_outputs(client, team)

    report = _call(client, team, "owner", "POST", "/api/v1/reports/generate",
                   {"thread_id": "t-shared", "report_type": "executive_summary"})
    current["report/generate"] = {
        "status": report.status_code,
        "filename": report.get_json()["filename"],
        "project_name": report.get_json()["project_name"],
        "analysis": json.loads(_normalize(team, json.dumps(report_calls[0], sort_keys=True).encode())),
    }
    email = _call(client, team, "owner", "POST", "/api/v1/email-assets/threads/t-shared",
                  {"idempotency_key": "p2c-owner-compat-1", "scorecard_id": team["projects"]["owner"][1],
                   "output_types": ["scorecards", "ranked_ideas"]})
    message = sent_emails[0]
    current["email/send"] = {
        "status": email.status_code,
        "subject": message["subject"],
        "text_sha256": hashlib.sha256(_normalize(team, message["text_body"].encode())).hexdigest(),
        "html_sha256": hashlib.sha256(_normalize(team, message["html_body"].encode())).hexdigest(),
        "attachments": [
            {"filename": a.filename, "content_type": a.content_type,
             "sha256": _attachment_digest(team, a.data)}
            for a in message["attachments"]
        ],
    }

    if os.environ.get("P2C_WRITE_OWNER_BASELINE") == "1":
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(current, indent=2, sort_keys=True) + "\n")
        pytest.skip("baseline recorded")

    baseline = json.loads(BASELINE.read_text())
    assert sorted(current) == sorted(baseline)
    for key in sorted(baseline):
        assert current[key] == baseline[key], key


def _attachment_digest(team, data):
    class _R:
        pass
    r = _R()
    r.data = data
    return _body_digest(team, r)
