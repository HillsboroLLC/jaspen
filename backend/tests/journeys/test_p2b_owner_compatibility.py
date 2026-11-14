"""H-2b acceptance: the owner's responses are byte-identical to P2a.

The same fixture project and the same owner requests are replayed here and
compared with ``fixtures/p2b_owner_baseline_p2a.json``, which was recorded on
P2a (commit 16ef19c8) with this file. Every difference is listed in
``APPROVED_DIFFERENCES`` with the exact P2a value and the exact P2b value; any
other byte that differs fails the test.

Only values produced during the run are normalized: member and organization
ids (random per run), scenario ids the server generates, and timestamps
within a day of now. Timestamps stored in the fixture are compared as is.

Re-record the baseline (only on P2a, never on P2b):
    P2B_WRITE_OWNER_BASELINE=1 pytest tests/journeys/test_p2b_owner_compatibility.py
"""

import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from tests.journeys.test_p2b_workspace_project_access import (  # noqa: F401 (fixtures)
    _call,
    _no_rate_limits,
    _seed_populated_plan,
    solo,
    team,
)

BASELINE = Path(__file__).parent / "fixtures" / "p2b_owner_baseline_p2a.json"

# Each entry: "sequence/request" -> {JSON path: (P2a value, P2b value)}.
#
# Revision numbers (no write on read, spec 2.3): P2a's reads of the plan and
# bundle saved the project and bumped its revision, so every later response
# carries a higher number on P2a. P2b's reads save nothing.
#
# The legacy-plan fix (Codex P2b review): opening an option by its own id
# found no plan on P2a when the plan was stored under a stale key; P2b returns
# that option's plan, named for it, without saving.
_LEGACY_PLAN_FOR_ITS_OPTION = {
    "idea_name": "Title MARKER-P2B-7Q",
    "name": "Title MARKER-P2B-7Q \u2014 Execution Plan",
    "phases": [],
    "scorecard_id": "t-shared-card",
    "scorecard_name": "Title MARKER-P2B-7Q",
    "tasks": [{"id": "t1", "status": "todo", "title": "Kickoff for Title MARKER-P2B-7Q"}],
}
APPROVED_DIFFERENCES = {
    "workspace/wbs": {"revision": (4, 2)},
    "plan-and-chat/wbs-canonical-id-first-open": {
        "revision": (5, 3),
        "project_wbs": (None, _LEGACY_PLAN_FOR_ITS_OPTION),
    },
    "plan-and-chat/wbs-legacy-route": {"revision": (7, 3)},
    "plan-and-chat/wbs-save": {"revision": (10, 5)},
    "plan-and-chat/wbs-reopen": {"revision": (10, 5)},
}

_ISO = re.compile(r'"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})?)"')
_EPOCH_MS = re.compile(r'(?<![\d.])(1\d{12})(?![\d.])')


def _normalize(team, text, generated_ids):
    for name, user in team["users"].items():
        text = text.replace(str(user.id), f"<user:{name}>")
    text = text.replace(str(team["org"].id), "<org>")
    for index, value in enumerate(generated_ids):
        text = text.replace(value, f"<generated:{index}>")
    now = datetime.utcnow()

    def _iso(match):
        raw = match.group(1)
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(tzinfo=None)
        except ValueError:
            return match.group(0)
        return '"<now>"' if abs(stamp - now) < timedelta(days=1) else match.group(0)

    def _epoch(match):
        stamp = datetime.utcfromtimestamp(int(match.group(1)) / 1000)
        return "<now-ms>" if abs(stamp - now) < timedelta(days=1) else match.group(0)

    return _EPOCH_MS.sub(_epoch, _ISO.sub(_iso, text))


def _record(client, team, out, generated_ids, key, method, path, body=None):
    response = _call(client, team, "owner", method, path, body)
    data = response.get_json(silent=True)
    if isinstance(data, dict) and key == "scenario-create" and data.get("scenario_id"):
        generated_ids.append(str(data["scenario_id"]))
    out[key] = [response.status_code, _normalize(team, response.get_data(as_text=True), generated_ids)]
    return data


def _workspace_sequence(client, team):
    t, c = team["projects"]["owner"]
    out, ids = {}, []
    for key, method, path, body in [
        ("bundle", "GET", f"/api/v1/strategy/threads/{t}/bundle", None),
        ("bundle-again", "GET", f"/api/v1/strategy/threads/{t}/bundle", None),
        ("wbs", "GET", f"/api/v1/strategy/threads/{t}/wbs", None),
        ("scorecard", "GET", f"/api/v1/strategy/threads/{t}/scorecards/{c}", None),
        ("overrides", "GET", f"/api/v1/strategy/threads/{t}/scorecards/{c}/overrides", None),
        ("attributes", "GET", f"/api/v1/strategy/threads/{t}/scorecards/{c}/attributes", None),
        ("selection", "POST", f"/api/v1/strategy/threads/{t}/selection", {"constraints": []}),
        ("adopt", "POST", f"/api/v1/strategy/threads/{t}/adopt", {"analysis_id": "scn-1"}),
        ("rename", "PATCH", f"/api/v1/strategy/threads/{t}/scorecard-snapshots/{c}", {"label": "Renamed"}),
        ("patch", "PATCH", f"/api/v1/strategy/threads/{t}/scorecard-patch", {"executive_summary": "Edited"}),
        ("bundle-after-edits", "GET", f"/api/v1/strategy/threads/{t}/bundle", None),
        ("score-delete", "DELETE", f"/api/v1/strategy/scores/{t}/{c}", None),
        ("bundle-final", "GET", f"/api/v1/strategy/threads/{t}/bundle", None),
    ]:
        _record(client, team, out, ids, key, method, path, body)
    return out


def _plan_and_chat_sequence(client, team):
    t, c = team["projects"]["owner"]
    _seed_populated_plan(t, c, team["users"]["owner"])
    out, ids = {}, []
    # Opening the option by its own id: P2a found no plan (Codex's finding).
    _record(client, team, out, ids, "wbs-canonical-id-first-open", "GET",
            f"/api/v1/strategy/threads/{t}/wbs?scorecard_id={c}")
    # The legacy plan route (no option id) names the plan's option.
    opened = _record(client, team, out, ids, "wbs-legacy-route", "GET", f"/api/v1/strategy/threads/{t}/wbs")
    _record(client, team, out, ids, "chat-legacy-key", "GET",
            f"/api/v1/strategy/threads/{t}/workspace-chat/__execution__::{c}")
    _record(client, team, out, ids, "chat-save", "PUT",
            f"/api/v1/strategy/threads/{t}/workspace-chat/__execution__",
            {"messages": [{"role": "user", "text": "Owner note"}]})
    _record(client, team, out, ids, "chat-read", "GET",
            f"/api/v1/strategy/threads/{t}/workspace-chat/__execution__")
    # The customer edits and saves the plan the workspace just showed them.
    opened = opened or {}
    plan = dict(opened.get("project_wbs") or {})
    plan["tasks"] = list(plan.get("tasks") or []) + [{"id": "t2", "title": "Owner follow-up", "status": "todo"}]
    _record(client, team, out, ids, "wbs-save", "PUT", f"/api/v1/strategy/threads/{t}/wbs",
            {"scorecard_id": opened.get("scorecard_id"), "project_wbs": plan,
             "expected_updated_at": plan.get("updated_at")})
    _record(client, team, out, ids, "wbs-reopen", "GET",
            f"/api/v1/strategy/threads/{t}/wbs?scorecard_id={c}")
    return out


def _scenario_sequence(client, team):
    t, _c = team["projects"]["owner"]
    out, ids = {}, []
    _record(client, team, out, ids, "scenario-list", "GET", f"/api/v1/strategy/threads/{t}/scenarios")
    _record(client, team, out, ids, "scenario-create", "POST", f"/api/v1/strategy/threads/{t}/scenarios",
            {"label": "Owner scenario", "deltas": {}})
    edited = _record(client, team, out, ids, "scenario-update", "PATCH",
                     f"/api/v1/strategy/scenarios/scn-1?thread_id={t}", {"label": "Renamed scenario"})
    _record(client, team, out, ids, "scenario-apply", "POST", f"/api/v1/strategy/scenarios/scn-1/apply?thread_id={t}",
            {"expected_updated_at": (edited or {}).get("updated_at")})
    _record(client, team, out, ids, "scenario-list-after", "GET", f"/api/v1/strategy/threads/{t}/scenarios")
    return out


SEQUENCES = {
    "workspace": _workspace_sequence,
    "plan-and-chat": _plan_and_chat_sequence,
    "scenarios": _scenario_sequence,
}


def _get_path(document, path):
    node = document
    for part in path.split("."):
        node = node[int(part)] if isinstance(node, list) else node[part]
    return node


def _set_path(document, path, value):
    parts = path.split(".")
    node = document
    for part in parts[:-1]:
        node = node[int(part)] if isinstance(node, list) else node[part]
    last = parts[-1]
    if isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value


@pytest.mark.parametrize("sequence", sorted(SEQUENCES))
def test_owner_responses_match_p2a(client, team, sequence):
    actual = SEQUENCES[sequence](client, team)

    if os.environ.get("P2B_WRITE_OWNER_BASELINE"):
        recorded = json.loads(BASELINE.read_text()) if BASELINE.exists() else {}
        recorded[sequence] = actual
        BASELINE.parent.mkdir(parents=True, exist_ok=True)
        BASELINE.write_text(json.dumps(recorded, indent=1, sort_keys=True) + "\n")
        pytest.skip("baseline recorded")

    expected = json.loads(BASELINE.read_text())[sequence]
    assert sorted(actual) == sorted(expected)
    for key in sorted(expected):
        p2a_status, p2a_body = expected[key]
        p2b_status, p2b_body = actual[key]
        assert p2b_status == p2a_status, (sequence, key)
        approved = APPROVED_DIFFERENCES.get(f"{sequence}/{key}", {})
        if not approved:
            assert p2b_body == p2a_body, (sequence, key)
            continue
        p2a_doc, p2b_doc = json.loads(p2a_body), json.loads(p2b_body)
        for path, (p2a_value, p2b_value) in approved.items():
            assert _get_path(p2a_doc, path) == p2a_value, (sequence, key, path, "P2a value")
            assert _get_path(p2b_doc, path) == p2b_value, (sequence, key, path, "P2b value")
            _set_path(p2a_doc, path, p2b_value)
        # With exactly the approved values substituted, the rest is identical.
        assert json.dumps(p2b_doc, sort_keys=True) == json.dumps(p2a_doc, sort_keys=True), (sequence, key)
