"""Phase 4: permission-aware organizational Decision Record retrieval.

The point of this phase is that Jaspen can retrieve the RIGHT organizational
decisions SAFELY -- not that recall is maximal. So the load-bearing tests here
are the authorization ones, especially that unauthorized records never reach
the ranker even momentarily.
"""
import pytest

from app import decision_retrieval
from app.decision_records import can_read_record, create_or_refresh_record
from app.decision_retrieval import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    authorized_candidates,
    rank,
    search,
    summarize,
)
from app.models import OrganizationMember, OrgIdeaLedger, UserSession
from app.models_decision_record import DecisionRecord

from tests.test_session_org_ownership import (
    _add_member,
    _headers,
    _mk_org,
    _mk_user,
    team_setup,
)
from tests.test_decision_record_pipeline import _seed_scored_project


@pytest.fixture
def retrieval_cast(db, team_setup):
    """One org with a record, plus a viewer and a genuine outsider."""
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    viewer = _mk_user(db, "r-viewer@acme.test")
    _add_member(db, org, viewer, role="viewer")

    outsider = _mk_user(db, "r-outsider@other.test")
    other_org = _mk_org(db, outsider, name="Rival")

    _seed_scored_project(db, org, owner, session_id="r-shared",
                         visibility="team", name="Warehouse automation")
    record, _ = create_or_refresh_record(owner, "r-shared")

    return {
        "org": org, "owner": owner, "editor": editor, "viewer": viewer,
        "outsider": outsider, "other_org": other_org, "record": record,
    }


# ── A / B / C / D. who can retrieve ──────────────────────────────────────────

def test_owner_retrieves_the_org_record(retrieval_cast):
    results = search(retrieval_cast["owner"], "warehouse")
    assert [r["id"] for r in results] == [retrieval_cast["record"].id]


def test_authorized_collaborator_retrieves_the_same_canonical_record(retrieval_cast):
    """B + 8: same record, same id, no per-user duplicate."""
    owner_results = search(retrieval_cast["owner"], "warehouse")
    editor_results = search(retrieval_cast["editor"], "warehouse")

    assert [r["id"] for r in editor_results] == [r["id"] for r in owner_results]
    assert DecisionRecord.query.filter_by(thread_id="r-shared").count() == 1


def test_viewer_can_read_but_not_mutate(client, app, db, retrieval_cast):
    viewer, record = retrieval_cast["viewer"], retrieval_cast["record"]
    assert can_read_record(record, viewer) is True

    resp = client.patch(f"/api/v1/decision-records/{record.id}",
                        headers=_headers(app, viewer),
                        json={"final_decision": "viewer tried to decide"})
    assert resp.status_code == 403
    assert DecisionRecord.query.get(record.id).final_decision is None


def test_outsider_retrieves_nothing_and_gets_404(client, app, retrieval_cast):
    outsider, record = retrieval_cast["outsider"], retrieval_cast["record"]

    assert search(outsider, "warehouse") == []
    assert can_read_record(record, outsider) is False

    resp = client.get(f"/api/v1/decision-records/{record.id}",
                      headers=_headers(app, outsider))
    assert resp.status_code == 404, "record existence was revealed to an outsider"


def test_removed_member_loses_retrieval(db, retrieval_cast):
    editor, record = retrieval_cast["editor"], retrieval_cast["record"]
    assert search(editor, "warehouse")

    OrganizationMember.query.filter_by(
        organization_id=retrieval_cast["org"].id, user_id=editor.id
    ).delete()
    db.session.commit()

    assert search(editor, "warehouse") == []
    assert can_read_record(record, editor) is False


def test_private_project_record_is_not_org_readable(db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_scored_project(db, org, owner, session_id="r-private",
                         visibility="private", name="Confidential restructure")
    create_or_refresh_record(owner, "r-private")

    assert search(owner, "restructure")
    assert search(editor, "restructure") == [], "a private project's record leaked"


def test_solo_user_record_remains_retrievable(db):
    solo = _mk_user(db, "r-solo@example.test", plan="free")
    org = _mk_org(db, solo, name="RSolo", plan="free")
    _seed_scored_project(db, org, solo, session_id="r-solo",
                         visibility="private", name="Solo pricing change")
    create_or_refresh_record(solo, "r-solo")

    results = search(solo, "pricing")
    assert len(results) == 1
    assert results[0]["organization_id"] == org.id


# ── F / G. organization scope, and the ordering rule ─────────────────────────

def test_retrieval_is_organization_scoped(db, retrieval_cast):
    """A second org's record never appears for the first org's members."""
    outsider, other_org = retrieval_cast["outsider"], retrieval_cast["other_org"]
    _seed_scored_project(db, other_org, outsider, session_id="r-rival",
                         visibility="team", name="Warehouse automation")
    create_or_refresh_record(outsider, "r-rival")

    owner_ids = {r["id"] for r in search(retrieval_cast["owner"], "warehouse")}
    outsider_ids = {r["id"] for r in search(outsider, "warehouse")}

    assert owner_ids and outsider_ids
    assert owner_ids.isdisjoint(outsider_ids)


def test_unauthorized_records_never_enter_the_ranked_candidate_set(db, retrieval_cast, monkeypatch):
    """G. The load-bearing test of this phase.

    Fails if anything unauthorized reaches the ranker -- even transiently,
    even if it would have been filtered out afterwards.
    """
    outsider, other_org = retrieval_cast["outsider"], retrieval_cast["other_org"]
    _seed_scored_project(db, other_org, outsider, session_id="r-secret",
                         visibility="team", name="Warehouse automation")
    secret, _ = create_or_refresh_record(outsider, "r-secret")

    seen = []
    real_rank = decision_retrieval.rank

    def _spy(records, query=None, **kwargs):
        seen.extend(records)
        return real_rank(records, query, **kwargs)

    monkeypatch.setattr(decision_retrieval, 'rank', _spy)

    decision_retrieval.search(retrieval_cast["owner"], "warehouse")

    assert seen, "precondition: the ranker was actually called"
    assert secret.id not in {r.id for r in seen}, (
        "an unauthorized record entered candidate assembly"
    )
    assert all(
        can_read_record(r, retrieval_cast["owner"]) for r in seen
    ), "the ranker was handed a record the caller may not read"


def test_ranking_is_pure_and_does_not_query(retrieval_cast):
    """rank() cannot re-widen the set: it only sees what it is given."""
    assert rank([], "warehouse") == []
    single = [retrieval_cast["record"]]
    assert rank(single, "warehouse") == single
    assert rank(single, "totally-unrelated-term") == []


# ── H / I / J. behaviour of the retrieval itself ─────────────────────────────

def test_retrieval_never_creates_or_mutates_records(db, retrieval_cast):
    record = retrieval_cast["record"]
    before = (record.updated_at, record.status, record.final_decision)
    count_before = DecisionRecord.query.count()

    for _ in range(3):
        search(retrieval_cast["owner"], "warehouse")

    refreshed = DecisionRecord.query.get(record.id)
    assert DecisionRecord.query.count() == count_before
    assert (refreshed.updated_at, refreshed.status, refreshed.final_decision) == before


def test_result_set_is_bounded(db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    for i in range(DEFAULT_LIMIT + 8):
        _seed_scored_project(db, org, owner, session_id=f"r-many-{i}",
                             visibility="team", name=f"Warehouse plan {i}")
        create_or_refresh_record(owner, f"r-many-{i}")

    assert len(search(owner, "warehouse")) == DEFAULT_LIMIT
    assert len(search(owner, "warehouse", limit=3)) == 3
    # The cap holds even when a caller asks for more.
    assert len(search(owner, "warehouse", limit=MAX_LIMIT + 500)) <= MAX_LIMIT


def test_ranking_is_deterministic_and_repeatable(db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    for i in range(5):
        _seed_scored_project(db, org, owner, session_id=f"r-det-{i}",
                             visibility="team", name=f"Pricing option {i}")
        create_or_refresh_record(owner, f"r-det-{i}")

    runs = [[r["id"] for r in search(owner, "pricing")] for _ in range(4)]
    assert all(run == runs[0] for run in runs)
    assert len(runs[0]) == 5


def test_structured_filters_narrow_deterministically(db, retrieval_cast):
    owner, record = retrieval_cast["owner"], retrieval_cast["record"]

    assert [r["id"] for r in search(owner, thread_id="r-shared")] == [record.id]
    assert search(owner, thread_id="does-not-exist") == []
    assert [r["id"] for r in search(owner, status="recorded")] == [record.id]
    assert search(owner, status="decided") == []
    # Pending vs decided is a structured filter, not a text match.
    assert [r["id"] for r in search(owner, human_decision=False)] == [record.id]
    assert search(owner, human_decision=True) == []


def test_requesting_another_orgs_scope_returns_nothing(retrieval_cast):
    owner, other_org = retrieval_cast["owner"], retrieval_cast["other_org"]
    assert search(owner, organization_id=other_org.id) == []


# ── K / L. adjacent sources stay out ─────────────────────────────────────────

def test_personal_user_memory_is_never_retrieved(db, retrieval_cast):
    owner = retrieval_cast["owner"]
    db.session.add(UserSession(
        user_id=owner.id, session_id="__user_memory__", name="__user_memory__",
        document_type="memory", created_by_user_id=owner.id,
        payload={"session_id": "__user_memory__",
                 "memory_facts": {"business_summary": "warehouse logistics"}},
    ))
    db.session.commit()

    results = search(owner, "warehouse")
    assert results, "precondition: retrieval returned something"
    assert all(r["source_type"] == "decision_record" for r in results)
    assert all(r["thread_id"] != "__user_memory__" for r in results)


def test_org_idea_ledger_is_never_retrieved(db, retrieval_cast):
    owner, org = retrieval_cast["owner"], retrieval_cast["org"]
    db.session.add(OrgIdeaLedger(
        organization_id=org.id, originating_user_id=owner.id,
        source_session_id="r-ledger", idea_category="warehouse",
        jaspen_score=80, outcome="active",
    ))
    db.session.commit()

    results = search(owner, "warehouse")
    assert all(r["source_type"] == "decision_record" for r in results)
    assert all(r["id"] != "r-ledger" for r in results)


# ── M / N. the summary shape ─────────────────────────────────────────────────

def test_summary_preserves_human_decision_state_accurately(db, retrieval_cast):
    from app.decision_records import record_final_decision

    owner, record = retrieval_cast["owner"], retrieval_cast["record"]

    pending = summarize(record)
    assert pending["human_decision"]["recorded"] is False
    assert pending["human_decision"]["summary"] is None
    assert pending["recommendation_summary"], "the AI recommendation was dropped"

    record_final_decision(record, "We will pilot in Rotterdam.", decided_by_user_id=owner.id)
    decided = summarize(DecisionRecord.query.get(record.id))
    assert decided["human_decision"]["recorded"] is True
    assert decided["human_decision"]["summary"] == "We will pilot in Rotterdam."
    assert decided["status"] == "decided"


def test_summary_does_not_assert_current_truth(retrieval_cast):
    """No supersession signal exists yet, so nothing may claim to be current."""
    summary = summarize(retrieval_cast["record"])
    assert summary["is_current"] is None
    assert summary["status"] == "recorded"
    assert summary["created_at"] and summary["updated_at"]


def test_summary_links_back_to_the_full_record(client, app, retrieval_cast):
    """N. Summaries are pointers, never replacements."""
    owner, record = retrieval_cast["owner"], retrieval_cast["record"]

    summary = search(owner, "warehouse")[0]
    assert summary["id"] == record.id
    assert summary["scorecard_ids"], "evidence linkage lost in the summary"
    # The summary is compact: no long-form payload rides along.
    assert "record" not in summary
    assert "conversation_summary" not in summary
    assert "scorecards" not in summary

    full = client.get(f"/api/v1/decision-records/{summary['id']}",
                      headers=_headers(app, owner))
    assert full.status_code == 200
    body = full.get_json()["record"]
    assert body["record"]["scorecard_ids"] == summary["scorecard_ids"]


def test_collaborator_sees_the_same_evidence_linkage(retrieval_cast):
    owner_summary = search(retrieval_cast["owner"], "warehouse")[0]
    editor_summary = search(retrieval_cast["editor"], "warehouse")[0]
    assert editor_summary["scorecard_ids"] == owner_summary["scorecard_ids"]
    assert editor_summary["id"] == owner_summary["id"]


# ── the HTTP surface ─────────────────────────────────────────────────────────

def test_search_endpoint_is_permission_scoped(client, app, db, retrieval_cast):
    owner, outsider = retrieval_cast["owner"], retrieval_cast["outsider"]

    ok = client.get("/api/v1/decision-records/search?q=warehouse",
                    headers=_headers(app, owner))
    assert ok.status_code == 200
    body = ok.get_json()
    assert body["count"] == 1
    assert body["source_types"] == ["decision_record"]
    assert body["results"][0]["id"] == retrieval_cast["record"].id

    empty = client.get("/api/v1/decision-records/search?q=warehouse",
                       headers=_headers(app, outsider))
    assert empty.status_code == 200
    assert empty.get_json()["results"] == []


def test_list_endpoint_is_org_scoped_not_user_scoped(client, app, retrieval_cast):
    """The Phase 3 consequence this phase exists to fix."""
    editor = retrieval_cast["editor"]
    resp = client.get("/api/v1/decision-records", headers=_headers(app, editor))
    assert resp.status_code == 200
    ids = [r["id"] for r in resp.get_json()["records"]]
    assert retrieval_cast["record"].id in ids, (
        "a collaborator could not list their own organization's decision"
    )
