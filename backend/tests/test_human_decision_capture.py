"""Phase 5.1: the human-decision capture flow, end to end over HTTP.

These exercise the endpoints the workspace panel actually calls, so the
guarantee being tested is the product one: a person can say "this is our
decision" and nothing else in the system can say it for them.
"""
import pytest

from app.decision_records import CURRENT, SUPERSEDED, UNKNOWN, create_or_refresh_record, current_state
from app.models import UserSession
from app.models_decision_record import DecisionRecord

from tests.test_session_org_ownership import (
    _add_member,
    _headers,
    _mk_org,
    _mk_user,
    team_setup,
)
from tests.test_decision_record_pipeline import _seed_scored_project


BASE = "/api/v1/decision-records"


def _record_for(db, org, creator, session_id, name, visibility="team"):
    _seed_scored_project(db, org, creator, session_id=session_id,
                         visibility=visibility, name=name)
    record, _ = create_or_refresh_record(creator, session_id)
    return record


@pytest.fixture
def capture_cast(db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    viewer = _mk_user(db, "h-viewer@acme.test")
    _add_member(db, org, viewer, role="viewer")
    outsider = _mk_user(db, "h-outsider@other.test")
    _mk_org(db, outsider, name="Rival")

    record = _record_for(db, org, owner, "h-thread", "Warehouse automation")
    return {"org": org, "owner": owner, "editor": editor, "viewer": viewer,
            "outsider": outsider, "record": record}


# ── A. the panel's data source ───────────────────────────────────────────────

def test_completed_analysis_exposes_a_record_with_state_and_permission(client, app, capture_cast):
    """What the panel loads: one record, its derived state, and can_edit."""
    owner = capture_cast["owner"]
    resp = client.get(f"{BASE}?thread_id=h-thread&limit=1", headers=_headers(app, owner))
    assert resp.status_code == 200
    records = resp.get_json()["records"]
    assert len(records) == 1
    assert records[0]["id"] == capture_cast["record"].id
    assert records[0]["current_state"] == UNKNOWN
    assert records[0]["can_edit"] is True
    assert records[0]["final_decision"] is None


def test_viewer_sees_state_and_recommendation_but_cannot_edit(client, app, capture_cast):
    viewer = capture_cast["viewer"]
    resp = client.get(f"{BASE}?thread_id=h-thread&limit=1", headers=_headers(app, viewer))
    assert resp.status_code == 200
    record = resp.get_json()["records"][0]
    assert record["can_edit"] is False
    assert record["current_state"] == UNKNOWN
    assert record["recommendation"]


def test_outsider_sees_no_record(client, app, capture_cast):
    resp = client.get(f"{BASE}?thread_id=h-thread", headers=_headers(app, capture_cast["outsider"]))
    assert resp.status_code == 200
    assert resp.get_json()["records"] == []


# ── B / C / D / F. recording the decision ────────────────────────────────────

def test_editor_records_a_final_decision(client, app, db, capture_cast):
    editor, record = capture_cast["editor"], capture_cast["record"]

    resp = client.patch(f"{BASE}/{record.id}", headers=_headers(app, editor),
                        json={"final_decision": "We will pilot in Rotterdam."})
    assert resp.status_code == 200, resp.get_json()

    body = resp.get_json()["record"]
    assert body["final_decision"] == "We will pilot in Rotterdam."
    assert body["status"] == "decided"
    assert body["current_state"] == CURRENT

    stored = DecisionRecord.query.get(record.id)
    assert stored.decided_at is not None
    assert stored.record["human_decision"]["recorded"] is True
    assert stored.record["human_decision"]["decided_by_user_id"] == editor.id


def test_viewer_cannot_record_a_decision(client, app, db, capture_cast):
    viewer, record = capture_cast["viewer"], capture_cast["record"]

    resp = client.patch(f"{BASE}/{record.id}", headers=_headers(app, viewer),
                        json={"final_decision": "Viewer decides"})
    assert resp.status_code == 403
    assert DecisionRecord.query.get(record.id).final_decision is None
    assert current_state(DecisionRecord.query.get(record.id)) == UNKNOWN


def test_outsider_cannot_record_and_cannot_discover(client, app, db, capture_cast):
    outsider, record = capture_cast["outsider"], capture_cast["record"]

    resp = client.patch(f"{BASE}/{record.id}", headers=_headers(app, outsider),
                        json={"final_decision": "Not yours"})
    assert resp.status_code == 404
    assert DecisionRecord.query.get(record.id).final_decision is None


def test_the_human_decision_may_contradict_the_recommendation(client, app, db, capture_cast):
    """D. The whole point of a separate act."""
    owner, record = capture_cast["owner"], capture_cast["record"]
    recommendation = record.record["recommendation"]
    assert recommendation

    client.patch(f"{BASE}/{record.id}", headers=_headers(app, owner),
                 json={"final_decision": "We are not proceeding at all."})

    stored = DecisionRecord.query.get(record.id)
    assert stored.final_decision == "We are not proceeding at all."
    assert stored.record["recommendation"] == recommendation, "the recommendation was overwritten"


def test_recording_creates_no_duplicate_record(client, app, db, capture_cast):
    """E + 10. The canonical record is mutated, never replaced."""
    owner, record = capture_cast["owner"], capture_cast["record"]
    before = DecisionRecord.query.count()

    client.patch(f"{BASE}/{record.id}", headers=_headers(app, owner),
                 json={"final_decision": "Approved."})

    assert DecisionRecord.query.count() == before
    assert DecisionRecord.query.filter_by(thread_id="h-thread").count() == 1


def test_collaborator_acts_on_the_same_canonical_record(client, app, db, capture_cast):
    """H. Owner created it; the editor decides on it. One record."""
    owner, editor, record = capture_cast["owner"], capture_cast["editor"], capture_cast["record"]

    resp = client.patch(f"{BASE}/{record.id}", headers=_headers(app, editor),
                        json={"final_decision": "Team decision."})
    assert resp.status_code == 200

    assert DecisionRecord.query.filter_by(thread_id="h-thread").count() == 1
    stored = DecisionRecord.query.get(record.id)
    # Authorship is unchanged; the decider is captured separately.
    assert stored.user_id == owner.id
    assert stored.record["human_decision"]["decided_by_user_id"] == editor.id


# ── G / M / N. nothing decides on the human's behalf ─────────────────────────

def test_an_undecided_record_stays_pending(client, app, capture_cast):
    owner = capture_cast["owner"]
    resp = client.get(f"{BASE}?thread_id=h-thread&limit=1", headers=_headers(app, owner))
    assert resp.get_json()["records"][0]["current_state"] == UNKNOWN


def test_rescoring_never_records_a_decision(db, capture_cast):
    """M + N. Analysis completing again is not a decision, and still works."""
    owner, record = capture_cast["owner"], capture_cast["record"]

    session_row = UserSession.query.filter_by(session_id="h-thread").one()
    payload = dict(session_row.payload)
    payload["portfolio_summary"] = {"recommended_sequence": "New advice entirely."}
    session_row.payload = payload
    db.session.commit()

    refreshed, created = create_or_refresh_record(owner, "h-thread")

    assert created is False
    assert refreshed.record["recommendation"] == "New advice entirely."
    assert refreshed.final_decision is None
    assert current_state(refreshed) == UNKNOWN
    assert DecisionRecord.query.filter_by(thread_id="h-thread").count() == 1


def test_a_recorded_decision_survives_a_later_rescore(db, client, app, capture_cast):
    owner, record = capture_cast["owner"], capture_cast["record"]
    client.patch(f"{BASE}/{record.id}", headers=_headers(app, owner),
                 json={"final_decision": "Locked in."})

    create_or_refresh_record(owner, "h-thread")

    stored = DecisionRecord.query.get(record.id)
    assert stored.final_decision == "Locked in."
    assert current_state(stored) == CURRENT


# ── J / K / L. supersession from the panel ───────────────────────────────────

def test_a_new_decision_can_supersede_a_visible_predecessor(client, app, db, capture_cast):
    org, owner, record = capture_cast["org"], capture_cast["owner"], capture_cast["record"]
    client.patch(f"{BASE}/{record.id}", headers=_headers(app, owner),
                 json={"final_decision": "Original plan."})

    successor = _record_for(db, org, owner, "h-thread-2", "Warehouse automation v2")
    client.patch(f"{BASE}/{successor.id}", headers=_headers(app, owner),
                 json={"final_decision": "Revised plan."})

    resp = client.post(f"{BASE}/{successor.id}/supersedes", headers=_headers(app, owner),
                       json={"supersedes_id": record.id})
    assert resp.status_code == 200, resp.get_json()

    assert current_state(DecisionRecord.query.get(record.id)) == SUPERSEDED
    assert current_state(DecisionRecord.query.get(successor.id)) == CURRENT


def test_the_predecessor_remains_readable_as_history(client, app, db, capture_cast):
    org, owner, record = capture_cast["org"], capture_cast["owner"], capture_cast["record"]
    client.patch(f"{BASE}/{record.id}", headers=_headers(app, owner),
                 json={"final_decision": "Original plan."})
    successor = _record_for(db, org, owner, "h-thread-3", "Warehouse v3")
    client.post(f"{BASE}/{successor.id}/supersedes", headers=_headers(app, owner),
                json={"supersedes_id": record.id})

    resp = client.get(f"{BASE}/{record.id}", headers=_headers(app, owner))
    assert resp.status_code == 200
    body = resp.get_json()["record"]
    assert body["final_decision"] == "Original plan.", "history was overwritten"
    assert body["current_state"] == SUPERSEDED


def test_the_predecessor_selector_never_offers_an_inaccessible_record(client, app, db, team_setup):
    """L. The selector is fed by the permission-scoped search endpoint."""
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    private = _record_for(db, org, owner, "h-private", "Confidential restructure",
                          visibility="private")
    _record_for(db, org, owner, "h-open", "Open project", visibility="team")

    resp = client.get(f"{BASE}/search?current=all&limit=25", headers=_headers(app, editor))
    assert resp.status_code == 200
    ids = {r["id"] for r in resp.get_json()["results"]}
    assert private.id not in ids
    assert "Confidential" not in resp.get_data(as_text=True)


def test_viewer_cannot_supersede(client, app, db, capture_cast):
    org, owner, viewer = capture_cast["org"], capture_cast["owner"], capture_cast["viewer"]
    successor = _record_for(db, org, owner, "h-thread-4", "Warehouse v4")

    resp = client.post(f"{BASE}/{successor.id}/supersedes", headers=_headers(app, viewer),
                       json={"supersedes_id": capture_cast["record"].id})
    assert resp.status_code == 403
    assert DecisionRecord.query.get(successor.id).supersedes_id is None


# ── I. private projects are not promoted ─────────────────────────────────────

def test_recording_a_decision_does_not_promote_a_private_project(client, app, db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    private = _record_for(db, org, owner, "h-priv", "Private restructure", visibility="private")

    resp = client.patch(f"{BASE}/{private.id}", headers=_headers(app, owner),
                        json={"final_decision": "We restructure in Q1."})
    assert resp.status_code == 200

    # Still invisible to the rest of the organization, and the project's own
    # visibility is untouched.
    assert client.get(f"{BASE}/{private.id}", headers=_headers(app, editor)).status_code == 404
    row = UserSession.query.filter_by(session_id="h-priv").one()
    assert row.visibility == "private"

    search = client.get(f"{BASE}/search?q=restructure&current=all", headers=_headers(app, editor))
    assert search.get_json()["results"] == []


# ── O. solo users ────────────────────────────────────────────────────────────

def test_solo_user_can_record_a_decision(client, app, db):
    solo = _mk_user(db, "h-solo@example.test", plan="free")
    org = _mk_org(db, solo, name="HSolo", plan="free")
    record = _record_for(db, org, solo, "h-solo-thread", "Solo pricing", visibility="private")

    resp = client.patch(f"{BASE}/{record.id}", headers=_headers(app, solo),
                        json={"final_decision": "Raising prices 8%."})
    assert resp.status_code == 200
    assert resp.get_json()["record"]["current_state"] == CURRENT
    assert DecisionRecord.query.filter_by(thread_id="h-solo-thread").count() == 1
