"""Phase 3: the Decision Record creation pipeline.

Decision Records are the durable source-of-truth artifact a future
organizational memory layer will retrieve. This phase makes the product
actually produce them; it does NOT build retrieval.

The two things most worth pinning here are that a record follows organization
ownership rather than forking per member, and that an AI recommendation is
never allowed to read as the organization's decision.
"""
import pytest

from app.decision_records import (
    canonical_context,
    create_or_refresh_record,
    record_final_decision,
)
from app.models import Scorecard, UserSession
from app.models_decision_record import DecisionRecord

from tests.test_session_org_ownership import (
    _add_member,
    _mk_org,
    _mk_user,
    _seed_project,
    team_setup,
)


SCORED_RESULT = {
    "analysis_id": "an-1",
    "project_name": "Warehouse automation",
    "jaspen_score": 72,
    "score_category": "promising",
    "dimensions": {
        "market": {"label": "Market", "score": 80, "confidence": "high", "source": "connector"},
        "execution": {"label": "Execution", "score": 64, "confidence": "medium", "source": "assumed"},
    },
    "executive_summary": "Automating inbound receiving looks viable.",
}


def _seed_scored_project(db, org, creator, session_id="dr-1", visibility="team",
                         name="Warehouse automation"):
    """A project in the state the product leaves it in after a completed score."""
    row = _seed_project(db, org, creator, session_id=session_id, visibility=visibility)
    # One analysis id per project: scorecard ids are globally unique.
    analysis_id = f"an-{session_id}"
    result = {**SCORED_RESULT, "analysis_id": analysis_id, "project_name": name}

    payload = dict(row.payload)
    payload.update({
        "name": name,
        "status": "completed",
        "result": dict(result),
        "chat_history": [
            {"role": "user", "content": "Should we automate inbound receiving?"},
            {"role": "assistant", "content": "Here is the analysis."},
        ],
        "scoring_rubric": {"criteria": [{"key": "market", "weight": 0.6}]},
        "portfolio_summary": {"recommended_sequence": "Pilot in one facility first."},
        "strategy_objective": "balanced",
    })
    row.payload = payload
    row.status = "completed"
    row.name = name
    db.session.commit()

    # The durable Scorecard row is the PERSISTED COPY of the session result,
    # so it carries the same analysis id. Giving it a different one would seed
    # the same option twice and misrepresent how the product stores evidence.
    db.session.add(Scorecard(
        id=analysis_id, user_id=creator.id, organization_id=org.id,
        thread_id=session_id, project_name=name, data=dict(result),
    ))
    db.session.commit()
    return row


# ── A / B. what triggers a record ────────────────────────────────────────────

def test_completed_decision_creates_a_record(db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_scored_project(db, org, owner, session_id="dr-create")

    record, created = create_or_refresh_record(owner, "dr-create")

    assert created is True
    assert record.thread_id == "dr-create"
    assert record.status == "recorded"
    assert DecisionRecord.query.count() == 1


def test_ordinary_conversation_does_not_create_a_record(db, team_setup):
    """No scored artifact, nothing to record."""
    org, owner = team_setup["org"], team_setup["owner"]
    row = _seed_project(db, org, owner, session_id="dr-chat", visibility="team")
    payload = dict(row.payload)
    payload["chat_history"] = [{"role": "user", "content": "just thinking out loud"}]
    row.payload = payload
    db.session.commit()

    record, _created = create_or_refresh_record(owner, "dr-chat")
    # A record may exist as a shell, but it must not claim to be analysis.
    assert record.status == "in_analysis"
    assert record.record.get("scorecards") == []


def test_a_thread_with_no_content_at_all_raises(db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    with pytest.raises(LookupError):
        create_or_refresh_record(owner, "dr-nonexistent")


# ── C / D. idempotency ───────────────────────────────────────────────────────

def test_repeated_completion_refreshes_rather_than_duplicates(db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_scored_project(db, org, owner, session_id="dr-idem")

    first, created_first = create_or_refresh_record(owner, "dr-idem")
    second, created_second = create_or_refresh_record(owner, "dr-idem")
    third, _ = create_or_refresh_record(owner, "dr-idem")

    assert created_first is True
    assert created_second is False
    assert first.id == second.id == third.id
    assert DecisionRecord.query.filter_by(thread_id="dr-idem").count() == 1


def test_separate_projects_create_separate_records(db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_scored_project(db, org, owner, session_id="dr-a", name="Project A")
    _seed_scored_project(db, org, owner, session_id="dr-b", name="Project B")

    a, _ = create_or_refresh_record(owner, "dr-a")
    b, _ = create_or_refresh_record(owner, "dr-b")

    assert a.id != b.id
    assert DecisionRecord.query.count() == 2


# ── E / F / G. ownership and attribution ─────────────────────────────────────

def test_organization_id_comes_from_the_canonical_project(db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_scored_project(db, org, owner, session_id="dr-org")

    record, _ = create_or_refresh_record(owner, "dr-org")
    assert record.organization_id == org.id


def test_organization_comes_from_the_row_not_the_actor(db, team_setup):
    """Ownership is read off the canonical project, never off the caller."""
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    row = _seed_scored_project(db, org, owner, session_id="dr-org2")

    _r, resolved_org, attribution = canonical_context(editor, "dr-org2")
    assert resolved_org == row.organization_id == org.id
    assert attribution == owner.id, "attribution followed the caller, not the creator"


def test_no_resolvable_project_means_no_guessed_organization(db, team_setup):
    """A member acting in a different organization must not misfile a record."""
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_scored_project(db, org, owner, session_id="dr-org3")

    other_org = _mk_org(db, _mk_user(db, "dr-elsewhere@other.test"), name="Elsewhere")
    editor.active_organization_id = other_org.id
    db.session.commit()

    _row, resolved_org, _attr = canonical_context(editor, "dr-org3")
    assert resolved_org is None, "an organization was guessed from the actor"

    # ...and nothing is written under the wrong organization.
    with pytest.raises(LookupError):
        create_or_refresh_record(editor, "dr-org3")
    assert DecisionRecord.query.filter_by(organization_id=other_org.id).count() == 0


def test_creator_attribution_is_preserved(db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_scored_project(db, org, owner, session_id="dr-attr")

    record, _ = create_or_refresh_record(owner, "dr-attr")
    assert record.user_id == owner.id
    assert record.record["attribution"]["created_by_user_id"] == owner.id


def test_collaborator_refresh_does_not_fork_a_second_record(db, team_setup):
    """The Phase 1 fork, at the Decision Record layer."""
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_scored_project(db, org, owner, session_id="dr-fork")

    first, created_first = create_or_refresh_record(owner, "dr-fork")
    second, created_second = create_or_refresh_record(editor, "dr-fork")

    assert created_first is True
    assert created_second is False, "a collaborator forked the decision record"
    assert first.id == second.id
    assert DecisionRecord.query.filter_by(thread_id="dr-fork").count() == 1

    # Authorship stayed with the creator; the collaborator is a contributor.
    assert second.user_id == owner.id
    assert second.record["attribution"]["created_by_user_id"] == owner.id
    assert second.record["attribution"]["last_refreshed_by_user_id"] == editor.id


def test_collaborator_derives_the_same_evidence_set(db, team_setup):
    """Reading under the attribution identity, not the caller's."""
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    _seed_scored_project(db, org, owner, session_id="dr-eve")

    by_owner, _ = create_or_refresh_record(owner, "dr-eve")
    owner_ids = list(by_owner.record["scorecard_ids"])
    assert owner_ids, "precondition: the owner's derivation found evidence"

    by_editor, _ = create_or_refresh_record(editor, "dr-eve")
    assert list(by_editor.record["scorecard_ids"]) == owner_ids


# ── H. AI recommendation is never the human decision ─────────────────────────

def test_recommendation_is_not_treated_as_the_final_decision(db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_scored_project(db, org, owner, session_id="dr-human")

    record, _ = create_or_refresh_record(owner, "dr-human")

    assert record.record["recommendation"] == "Pilot in one facility first."
    assert record.final_decision is None
    assert record.status == "recorded"
    assert record.status != "decided"
    assert record.decided_at is None

    human = record.record["human_decision"]
    assert human["recorded"] is False
    assert human["decision"] is None


def test_recording_a_human_decision_advances_the_record(db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_scored_project(db, org, owner, session_id="dr-decided")
    record, _ = create_or_refresh_record(owner, "dr-decided")

    record_final_decision(record, "We will pilot in Rotterdam in Q4.",
                          decided_by_user_id=owner.id)

    assert record.status == "decided"
    assert record.final_decision == "We will pilot in Rotterdam in Q4."
    human = record.record["human_decision"]
    assert human["recorded"] is True
    assert human["decided_by_user_id"] == owner.id


def test_a_refresh_never_erases_a_recorded_human_decision(db, team_setup):
    """Re-scoring must not reset the decision back to 'none'."""
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_scored_project(db, org, owner, session_id="dr-keep")
    record, _ = create_or_refresh_record(owner, "dr-keep")
    record_final_decision(record, "Approved.", decided_by_user_id=owner.id)

    refreshed, created = create_or_refresh_record(owner, "dr-keep")

    assert created is False
    assert refreshed.final_decision == "Approved."
    assert refreshed.status == "decided", "a re-derivation regressed a decided record"
    assert refreshed.record["human_decision"]["recorded"] is True


# ── I. evidence linkage ──────────────────────────────────────────────────────

def test_scorecard_evidence_stays_separately_addressable(db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_scored_project(db, org, owner, session_id="dr-cards")

    record, _ = create_or_refresh_record(owner, "dr-cards")

    cards = record.record["scorecards"]
    assert cards, "no scorecards linked into the record"
    assert all(c.get("id") for c in cards), "a scorecard lost its stable id"
    assert record.record["scorecard_ids"] == [c["id"] for c in cards]
    # Dimensions survive rather than being flattened into prose.
    assert cards[0]["dimensions"]["market"]["score"] == 80


def test_evidence_summary_is_derived_not_narrated(db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_scored_project(db, org, owner, session_id="dr-evsum")

    record, _ = create_or_refresh_record(owner, "dr-evsum")
    summary = record.record["evidence_summary"]
    assert summary["graded_dimensions"] == 2
    assert summary["dimension_confidence_counts"]["high"] == 1


# ── J / K. adjacent layers stay separate ─────────────────────────────────────

def test_user_memory_sentinel_is_untouched_by_record_creation(db, team_setup):
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_scored_project(db, org, owner, session_id="dr-mem")
    db.session.add(UserSession(
        user_id=owner.id, session_id="__user_memory__", name="__user_memory__",
        document_type="memory", created_by_user_id=owner.id,
        payload={"session_id": "__user_memory__", "memory_facts": {"industry": "logistics"}},
    ))
    db.session.commit()

    create_or_refresh_record(owner, "dr-mem")

    sentinel = UserSession.query.filter_by(
        user_id=owner.id, session_id="__user_memory__"
    ).one()
    assert sentinel.organization_id is None
    assert sentinel.payload["memory_facts"] == {"industry": "logistics"}
    assert DecisionRecord.query.filter_by(thread_id="__user_memory__").count() == 0


def test_org_idea_ledger_is_not_used_as_the_record_source(db, team_setup):
    """Ledger = de-identified benchmarking. Records = decision narrative."""
    from app.models import OrgIdeaLedger

    org, owner = team_setup["org"], team_setup["owner"]
    _seed_scored_project(db, org, owner, session_id="dr-ledger")

    create_or_refresh_record(owner, "dr-ledger")

    # Record creation neither reads from nor writes to the ledger.
    assert OrgIdeaLedger.query.count() == 0


# ── L. solo users ────────────────────────────────────────────────────────────

def test_solo_user_gets_a_record_owned_by_their_solo_org(db):
    solo = _mk_user(db, "dr-solo@example.test", plan="free")
    org = _mk_org(db, solo, name="DrSolo", plan="free")
    _seed_scored_project(db, org, solo, session_id="dr-solo", visibility="private")

    record, created = create_or_refresh_record(solo, "dr-solo")

    assert created is True
    assert record.organization_id == org.id
    assert record.user_id == solo.id
    assert record.status == "recorded"


def test_solo_user_rescore_still_refreshes_one_record(db):
    solo = _mk_user(db, "dr-solo2@example.test", plan="free")
    org = _mk_org(db, solo, name="DrSolo2", plan="free")
    _seed_scored_project(db, org, solo, session_id="dr-solo2", visibility="private")

    create_or_refresh_record(solo, "dr-solo2")
    create_or_refresh_record(solo, "dr-solo2")
    assert DecisionRecord.query.filter_by(thread_id="dr-solo2").count() == 1


# ── legacy records are adopted, not duplicated ───────────────────────────────

def test_a_pre_phase_3_per_user_record_is_adopted(db, team_setup):
    """Records written under the old (user_id, thread_id) identity."""
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_scored_project(db, org, owner, session_id="dr-legacy")

    legacy = DecisionRecord(
        user_id=owner.id, organization_id=None, thread_id="dr-legacy",
        title="Legacy", status="recorded", record={},
    )
    db.session.add(legacy)
    db.session.commit()

    adopted, created = create_or_refresh_record(owner, "dr-legacy")
    assert created is False
    assert adopted.id == legacy.id
    assert DecisionRecord.query.filter_by(thread_id="dr-legacy").count() == 1


# ── the live trigger: the actual scoring endpoint ────────────────────────────
#
# Everything above exercises the record semantics directly. These two drive the
# real POST /api/v1/strategy/analyze path with the provider stubbed, so the
# wiring itself is covered rather than assumed.

def _stub_scorer(monkeypatch, score=76):
    from app.routes import ai_agent, strategy

    monkeypatch.setattr(strategy, 'get_llm_client', lambda: object())
    monkeypatch.setattr(
        strategy,
        '_generate_jaspen_scorecard',
        lambda *_a, **_k: ({
            'name': 'Scored project',
            'project_name': 'Scored project',
            'jaspen_score': score,
            'dimensions': {
                'market': {'label': 'Market', 'score': 80,
                           'confidence': 'high', 'source': 'connector'},
            },
        }, {
            'provider': 'anthropic', 'model': 'claude-test', 'model_type': 'pluto',
            'input_tokens': 100, 'output_tokens': 50,
        }),
    )
    # Personal memory extraction is a separate layer and spawns a thread.
    monkeypatch.setattr(ai_agent, 'extract_and_update_user_memory', lambda *_a, **_k: None)


def test_scoring_endpoint_creates_a_decision_record(client, db, team_setup, app, monkeypatch):
    """A. The completed-score path produces the durable record."""
    from flask_jwt_extended import create_access_token

    org, owner = team_setup["org"], team_setup["owner"]
    _seed_project(db, org, owner, session_id="dr-live", visibility="team")
    _stub_scorer(monkeypatch)

    with app.app_context():
        headers = {"Authorization": f"Bearer {create_access_token(identity=str(owner.id))}"}

    resp = client.post('/api/v1/strategy/analyze', headers=headers,
                       json={'thread_id': 'dr-live', 'description': 'Score this project'})
    assert resp.status_code == 200, resp.get_json()

    record = DecisionRecord.query.filter_by(thread_id='dr-live').one()
    assert record.organization_id == org.id
    assert record.user_id == owner.id
    assert record.status == 'recorded'
    # The model's output did NOT become the organization's decision.
    assert record.final_decision is None
    assert record.record['human_decision']['recorded'] is False


def test_rescoring_through_the_endpoint_refreshes_one_record(client, db, team_setup, app, monkeypatch):
    """C. Re-scoring is a refresh, not an accumulation."""
    from flask_jwt_extended import create_access_token

    org, owner = team_setup["org"], team_setup["owner"]
    _seed_project(db, org, owner, session_id="dr-live2", visibility="team")
    _stub_scorer(monkeypatch)

    with app.app_context():
        headers = {"Authorization": f"Bearer {create_access_token(identity=str(owner.id))}"}

    for _ in range(3):
        resp = client.post('/api/v1/strategy/analyze', headers=headers,
                           json={'thread_id': 'dr-live2', 'description': 'Score this project'})
        assert resp.status_code == 200, resp.get_json()

    assert DecisionRecord.query.filter_by(thread_id='dr-live2').count() == 1
