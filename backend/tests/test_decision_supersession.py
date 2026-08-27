"""Phase 5: supersession, and current vs historical decision state.

The two claims this phase must not get wrong:

  * A refresh is not a supersession. Re-scoring improves the analysis; it does
    not mean the organization changed its mind.
  * "No successor" is not the same as "current". A record nobody ever decided
    on is UNKNOWN, not the organization's standing position.
"""
import pytest

from app.decision_records import (
    CURRENT,
    SUPERSEDED,
    UNKNOWN,
    clear_supersession,
    create_or_refresh_record,
    current_state,
    record_final_decision,
    supersede_record,
    supersession_chain,
    successor_of,
)
from app.decision_retrieval import search, summarize
from app.models_decision_record import DecisionRecord

from tests.test_session_org_ownership import (
    _add_member,
    _headers,
    _mk_org,
    _mk_user,
    team_setup,
)
from tests.test_decision_record_pipeline import _seed_scored_project


def _record_for(db, org, creator, session_id, name, visibility="team"):
    _seed_scored_project(db, org, creator, session_id=session_id,
                         visibility=visibility, name=name)
    record, _ = create_or_refresh_record(creator, session_id)
    return record


@pytest.fixture
def chain_cast(db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    viewer = _mk_user(db, "s-viewer@acme.test")
    _add_member(db, org, viewer, role="viewer")
    outsider = _mk_user(db, "s-outsider@other.test")
    other_org = _mk_org(db, outsider, name="Rival")

    first = _record_for(db, org, owner, "s-first", "Pricing model v1")
    second = _record_for(db, org, owner, "s-second", "Pricing model v2")

    return {"org": org, "owner": owner, "editor": editor, "viewer": viewer,
            "outsider": outsider, "other_org": other_org,
            "first": first, "second": second}


# ── A / O. refresh is not supersession ───────────────────────────────────────

def test_refreshing_the_same_decision_creates_no_supersession(db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    record = _record_for(db, org, owner, "s-refresh", "Pricing model")

    for _ in range(3):
        again, created = create_or_refresh_record(owner, "s-refresh")
        assert created is False
        assert again.id == record.id

    assert DecisionRecord.query.filter_by(thread_id="s-refresh").count() == 1
    assert record.supersedes_id is None
    assert successor_of(record) is None


def test_a_changed_ai_recommendation_alone_never_supersedes(db, team_setup):
    """O. A model changing its mind is not the organization changing its mind."""
    org, owner = team_setup["org"], team_setup["owner"]
    record = _record_for(db, org, owner, "s-airec", "Market entry")

    row_payload = dict(record.record)
    assert row_payload.get("recommendation")

    # Re-derive with a different recommendation in the source project.
    from app.models import UserSession
    session_row = UserSession.query.filter_by(session_id="s-airec").one()
    payload = dict(session_row.payload)
    payload["portfolio_summary"] = {"recommended_sequence": "Actually, do the opposite."}
    session_row.payload = payload
    db.session.commit()

    refreshed, created = create_or_refresh_record(owner, "s-airec")

    assert created is False
    assert refreshed.record["recommendation"] == "Actually, do the opposite."
    assert refreshed.supersedes_id is None, "an AI recommendation change created supersession"
    assert DecisionRecord.query.filter_by(thread_id="s-airec").count() == 1


# ── B / C / D / E. explicit supersession ─────────────────────────────────────

def test_a_new_decision_can_supersede_a_prior_one(db, chain_cast):
    owner, first, second = chain_cast["owner"], chain_cast["first"], chain_cast["second"]

    supersede_record(second, first, owner)

    assert second.supersedes_id == first.id
    assert second.superseded_at is not None
    assert successor_of(first).id == second.id


def test_the_prior_record_remains_fully_readable(db, chain_cast):
    owner, first, second = chain_cast["owner"], chain_cast["first"], chain_cast["second"]
    original_title = first.title
    original_payload = dict(first.record)

    supersede_record(second, first, owner)

    survivor = DecisionRecord.query.get(first.id)
    assert survivor is not None
    assert survivor.title == original_title
    assert dict(survivor.record) == original_payload, "superseding rewrote history"


def test_predecessor_is_superseded_and_successor_may_be_current(db, chain_cast):
    owner, first, second = chain_cast["owner"], chain_cast["first"], chain_cast["second"]

    supersede_record(second, first, owner)
    assert current_state(first) == SUPERSEDED

    # The successor is only CURRENT once a human actually decided on it.
    assert current_state(second) == UNKNOWN
    record_final_decision(second, "We adopt pricing model v2.", decided_by_user_id=owner.id)
    assert current_state(second) == CURRENT


def test_clearing_supersession_restores_both(db, chain_cast):
    owner, first, second = chain_cast["owner"], chain_cast["first"], chain_cast["second"]
    supersede_record(second, first, owner)
    assert current_state(first) == SUPERSEDED

    clear_supersession(second)
    assert current_state(first) == UNKNOWN
    assert successor_of(first) is None


# ── N. unknown stays unknown ─────────────────────────────────────────────────

def test_a_never_decided_record_is_unknown_not_current(db, chain_cast):
    """The distinction the whole state model exists for."""
    first = chain_cast["first"]
    assert successor_of(first) is None
    assert first.final_decision is None
    assert current_state(first) == UNKNOWN, "a record nobody decided was called current"

    summary = summarize(first)
    assert summary["current_state"] == UNKNOWN
    assert summary["is_current"] is None, "unknown was rounded up to current"


def test_recency_alone_does_not_confer_current_state(db, chain_cast):
    """A later analysis is not automatically a new organizational decision."""
    first, second = chain_cast["first"], chain_cast["second"]
    assert second.created_at >= first.created_at
    assert current_state(second) == UNKNOWN
    assert current_state(first) == UNKNOWN


def test_a_decided_record_with_no_successor_is_current(db, chain_cast):
    owner, first = chain_cast["owner"], chain_cast["first"]
    record_final_decision(first, "We ship v1.", decided_by_user_id=owner.id)
    assert current_state(first) == CURRENT
    assert summarize(first)["is_current"] is True


# ── F / G / H / I. the guards ────────────────────────────────────────────────

def test_cross_organization_supersession_is_rejected(db, chain_cast):
    owner, second = chain_cast["owner"], chain_cast["second"]
    outsider, other_org = chain_cast["outsider"], chain_cast["other_org"]
    foreign = _record_for(db, other_org, outsider, "s-foreign", "Their pricing")

    # The owner cannot even see it, so this must not disclose that it exists.
    with pytest.raises(LookupError):
        supersede_record(second, foreign, owner)
    assert second.supersedes_id is None


def test_cross_organization_is_rejected_even_when_both_are_readable(db, team_setup):
    """A user in two organizations still cannot link across them."""
    org_a, owner = team_setup["org"], team_setup["owner"]
    org_b = _mk_org(db, _mk_user(db, "s-b-owner@b.test"), name="OrgB")
    _add_member(db, org_b, owner, role="admin")

    a_record = _record_for(db, org_a, owner, "s-cross-a", "A decision")
    b_record = _record_for(db, org_b, owner, "s-cross-b", "B decision")

    with pytest.raises(ValueError, match="same organization"):
        supersede_record(b_record, a_record, owner)
    assert b_record.supersedes_id is None


def test_self_supersession_is_rejected(db, chain_cast):
    owner, first = chain_cast["owner"], chain_cast["first"]
    with pytest.raises(ValueError, match="cannot supersede itself"):
        supersede_record(first, first, owner)
    assert first.supersedes_id is None


def test_a_cycle_is_rejected(db, chain_cast):
    owner, first, second = chain_cast["owner"], chain_cast["first"], chain_cast["second"]
    supersede_record(second, first, owner)

    with pytest.raises(ValueError, match="cycle"):
        supersede_record(first, second, owner)
    assert first.supersedes_id is None


def test_a_longer_cycle_is_rejected(db, chain_cast):
    org, owner = chain_cast["org"], chain_cast["owner"]
    first, second = chain_cast["first"], chain_cast["second"]
    third = _record_for(db, org, owner, "s-third", "Pricing model v3")

    supersede_record(second, first, owner)
    supersede_record(third, second, owner)

    with pytest.raises(ValueError, match="cycle"):
        supersede_record(first, third, owner)


def test_double_supersession_of_one_record_is_rejected(db, chain_cast):
    org, owner = chain_cast["org"], chain_cast["owner"]
    first, second = chain_cast["first"], chain_cast["second"]
    rival = _record_for(db, org, owner, "s-rival", "Pricing model v2b")

    supersede_record(second, first, owner)
    with pytest.raises(ValueError, match="already been superseded"):
        supersede_record(rival, first, owner)


def test_a_viewer_cannot_create_supersession(client, app, db, chain_cast):
    viewer, first, second = chain_cast["viewer"], chain_cast["first"], chain_cast["second"]

    resp = client.post(f"/api/v1/decision-records/{second.id}/supersedes",
                       headers=_headers(app, viewer),
                       json={"supersedes_id": first.id})
    assert resp.status_code == 403
    assert DecisionRecord.query.get(second.id).supersedes_id is None


def test_an_outsider_cannot_create_supersession(client, app, db, chain_cast):
    outsider, first, second = chain_cast["outsider"], chain_cast["first"], chain_cast["second"]

    resp = client.post(f"/api/v1/decision-records/{second.id}/supersedes",
                       headers=_headers(app, outsider),
                       json={"supersedes_id": first.id})
    assert resp.status_code == 404, "record existence leaked to an outsider"
    assert DecisionRecord.query.get(second.id).supersedes_id is None


# ── J. privacy of inaccessible chain links ───────────────────────────────────

def test_an_inaccessible_predecessor_is_redacted_not_disclosed(db, team_setup):
    """J. B is visible; A is private. The chain must not leak A."""
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]

    private = _record_for(db, org, owner, "s-priv", "Confidential restructure",
                          visibility="private")
    public = _record_for(db, org, owner, "s-pub", "Public follow-up",
                         visibility="team")
    supersede_record(public, private, owner)

    # The owner sees the whole chain.
    owner_chain = supersession_chain(public, owner)
    assert owner_chain["supersedes"][0]["accessible"] is True
    assert owner_chain["supersedes"][0]["title"] == "Confidential restructure"

    # The collaborator sees that something exists, and nothing about it.
    editor_chain = supersession_chain(public, editor)
    link = editor_chain["supersedes"][0]
    assert link["accessible"] is False
    assert link["id"] is None
    assert link["title"] is None
    assert "Confidential" not in str(link)


def test_history_endpoint_redacts_for_unauthorized_links(client, app, db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    private = _record_for(db, org, owner, "s-priv2", "Secret plan", visibility="private")
    public = _record_for(db, org, owner, "s-pub2", "Follow-up", visibility="team")
    supersede_record(public, private, owner)

    resp = client.get(f"/api/v1/decision-records/{public.id}/history",
                      headers=_headers(app, editor))
    assert resp.status_code == 200
    body = resp.get_json()
    assert "Secret plan" not in resp.get_data(as_text=True)
    assert body["supersedes"][0]["accessible"] is False


# ── K / L / M. retrieval behaviour ───────────────────────────────────────────

def test_retrieval_prefers_records_nothing_has_replaced(db, chain_cast):
    owner, first, second = chain_cast["owner"], chain_cast["first"], chain_cast["second"]
    supersede_record(second, first, owner)

    ids = {r["id"] for r in search(owner, "pricing")}
    assert second.id in ids
    assert first.id not in ids, "a superseded record surfaced by default"


def test_history_remains_queryable_and_is_not_hidden(db, chain_cast):
    owner, first, second = chain_cast["owner"], chain_cast["first"], chain_cast["second"]
    supersede_record(second, first, owner)

    all_ids = {r["id"] for r in search(owner, "pricing", current="all")}
    assert {first.id, second.id}.issubset(all_ids)

    superseded_ids = {r["id"] for r in search(owner, "pricing", current=False)}
    assert superseded_ids == {first.id}


def test_naming_a_thread_returns_its_record_even_when_superseded(db, chain_cast):
    owner, first, second = chain_cast["owner"], chain_cast["first"], chain_cast["second"]
    supersede_record(second, first, owner)

    results = search(owner, thread_id="s-first")
    assert [r["id"] for r in results] == [first.id]
    assert results[0]["is_current"] is False


def test_current_filter_distinguishes_all_three_states(db, chain_cast):
    org, owner = chain_cast["org"], chain_cast["owner"]
    first, second = chain_cast["first"], chain_cast["second"]
    supersede_record(second, first, owner)
    record_final_decision(second, "Adopted.", decided_by_user_id=owner.id)
    unknown = _record_for(db, org, owner, "s-unknown", "Pricing sidebar")

    assert {r["id"] for r in search(owner, "pricing", current=True)} == {second.id}
    assert {r["id"] for r in search(owner, "pricing", current=False)} == {first.id}
    assert {r["id"] for r in search(owner, "pricing", current="unknown")} == {unknown.id}


def test_summary_reports_supersession_pointers(db, chain_cast):
    owner, first, second = chain_cast["owner"], chain_cast["first"], chain_cast["second"]
    supersede_record(second, first, owner)

    summary = summarize(DecisionRecord.query.get(second.id))
    assert summary["supersedes_id"] == first.id
    assert summary["superseded_at"] is not None


# ── 7. the chain ─────────────────────────────────────────────────────────────

def test_chain_reads_forwards_through_three_records(db, chain_cast):
    org, owner = chain_cast["org"], chain_cast["owner"]
    first, second = chain_cast["first"], chain_cast["second"]
    third = _record_for(db, org, owner, "s-v3", "Pricing model v3")

    supersede_record(second, first, owner)
    supersede_record(third, second, owner)

    chain = supersession_chain(second, owner)
    assert [l["id"] for l in chain["supersedes"]] == [first.id]
    assert [l["id"] for l in chain["superseded_by"]] == [third.id]

    from_first = supersession_chain(first, owner)
    assert [l["id"] for l in from_first["superseded_by"]] == [second.id, third.id]
    assert from_first["current_state"] == SUPERSEDED


def test_chain_carries_metadata_not_payloads(db, chain_cast):
    owner, first, second = chain_cast["owner"], chain_cast["first"], chain_cast["second"]
    supersede_record(second, first, owner)

    link = supersession_chain(second, owner)["supersedes"][0]
    assert set(link) == {
        "accessible", "id", "title", "status", "current_state",
        "human_decision_recorded", "created_at", "superseded_at",
    }
    assert "record" not in link
    assert "scorecards" not in link


# ── P. solo users ────────────────────────────────────────────────────────────

def test_solo_user_supersession_works(db):
    solo = _mk_user(db, "s-solo@example.test", plan="free")
    org = _mk_org(db, solo, name="SSolo", plan="free")
    v1 = _record_for(db, org, solo, "s-solo-1", "Solo plan v1", visibility="private")
    v2 = _record_for(db, org, solo, "s-solo-2", "Solo plan v2", visibility="private")

    supersede_record(v2, v1, solo)
    assert current_state(v1) == SUPERSEDED

    record_final_decision(v2, "Going with v2.", decided_by_user_id=solo.id)
    assert current_state(v2) == CURRENT
    assert {r["id"] for r in search(solo, "solo plan")} == {v2.id}


def test_solo_user_refresh_still_creates_no_supersession(db):
    solo = _mk_user(db, "s-solo2@example.test", plan="free")
    org = _mk_org(db, solo, name="SSolo2", plan="free")
    record = _record_for(db, org, solo, "s-solo-r", "Solo refresh", visibility="private")

    create_or_refresh_record(solo, "s-solo-r")
    assert DecisionRecord.query.filter_by(thread_id="s-solo-r").count() == 1
    assert record.supersedes_id is None


# ── HTTP surface ─────────────────────────────────────────────────────────────

def test_supersession_endpoint_round_trip(client, app, db, chain_cast):
    owner, first, second = chain_cast["owner"], chain_cast["first"], chain_cast["second"]

    resp = client.post(f"/api/v1/decision-records/{second.id}/supersedes",
                       headers=_headers(app, owner),
                       json={"supersedes_id": first.id})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["record"]["supersedes_id"] == first.id
    assert body["chain"]["supersedes"][0]["id"] == first.id

    undo = client.delete(f"/api/v1/decision-records/{second.id}/supersedes",
                         headers=_headers(app, owner))
    assert undo.status_code == 200
    assert DecisionRecord.query.get(second.id).supersedes_id is None


def test_supersession_endpoint_rejects_self_reference(client, app, chain_cast):
    owner, first = chain_cast["owner"], chain_cast["first"]
    resp = client.post(f"/api/v1/decision-records/{first.id}/supersedes",
                       headers=_headers(app, owner),
                       json={"supersedes_id": first.id})
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "invalid_supersession"


def test_search_endpoint_exposes_the_current_filter(client, app, db, chain_cast):
    owner, first, second = chain_cast["owner"], chain_cast["first"], chain_cast["second"]
    supersede_record(second, first, owner)

    default = client.get("/api/v1/decision-records/search?q=pricing",
                         headers=_headers(app, owner)).get_json()
    assert {r["id"] for r in default["results"]} == {second.id}
    assert default["current"] == "not_superseded"

    everything = client.get("/api/v1/decision-records/search?q=pricing&current=all",
                            headers=_headers(app, owner)).get_json()
    assert {r["id"] for r in everything["results"]} == {first.id, second.id}
