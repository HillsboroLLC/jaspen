"""Phase 6: the outcome and lesson loop.

analysis -> recommendation -> human decision -> execution -> outcome -> lesson

The claims that matter: nothing fabricates an outcome, a lesson never
overwrites an earlier one, and both stay attached to the decision they came
from even when that decision is later superseded.
"""
import pytest

from app.decision_records import (
    OUTCOME_STATUSES,
    append_lesson,
    append_outcome,
    create_or_refresh_record,
    current_state,
    latest_outcome,
    record_final_decision,
    supersede_record,
)
from app.decision_retrieval import search, summarize
from app.models import User, UserSession
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


def _decided_record(db, org, creator, session_id, name, decision="We proceed.",
                    visibility="team"):
    _seed_scored_project(db, org, creator, session_id=session_id,
                         visibility=visibility, name=name)
    record, _ = create_or_refresh_record(creator, session_id)
    if decision:
        record_final_decision(record, decision, decided_by_user_id=creator.id)
    return record


@pytest.fixture
def loop_cast(db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    viewer = _mk_user(db, "o-viewer@acme.test")
    _add_member(db, org, viewer, role="viewer")
    outsider = _mk_user(db, "o-outsider@other.test")
    _mk_org(db, outsider, name="Rival")

    record = _decided_record(db, org, owner, "o-thread", "Warehouse automation")
    return {"org": org, "owner": owner, "editor": editor, "viewer": viewer,
            "outsider": outsider, "record": record}


# ── A / B / C. recording an outcome ──────────────────────────────────────────

def test_decided_record_accepts_an_explicit_outcome(client, app, db, loop_cast):
    owner, record = loop_cast["owner"], loop_cast["record"]

    resp = client.post(f"{BASE}/{record.id}/outcomes", headers=_headers(app, owner),
                       json={"summary": "Launched six weeks late, 18% over budget.",
                             "status": "partially_achieved"})
    assert resp.status_code == 201, resp.get_json()

    stored = DecisionRecord.query.get(record.id)
    outcome = latest_outcome(stored)
    assert outcome["summary"] == "Launched six weeks late, 18% over budget."
    assert outcome["status"] == "partially_achieved"
    assert stored.status == "outcome_recorded"
    assert stored.outcome_recorded_at is not None


def test_outcome_is_attributed_to_the_human_who_recorded_it(client, app, db, loop_cast):
    editor, record = loop_cast["editor"], loop_cast["record"]

    client.post(f"{BASE}/{record.id}/outcomes", headers=_headers(app, editor),
                json={"summary": "Shipped on time."})

    outcome = latest_outcome(DecisionRecord.query.get(record.id))
    assert outcome["recorded_by_user_id"] == editor.id
    assert outcome["recorded_by_name"]
    assert outcome["recorded_at"]


def test_nothing_creates_an_outcome_automatically(db, team_setup):
    """B. An analysis completing is not a result, and never becomes one."""
    org, owner = team_setup["org"], team_setup["owner"]
    _seed_scored_project(db, org, owner, session_id="o-auto", visibility="team")

    record, _ = create_or_refresh_record(owner, "o-auto")
    assert record.outcomes == []
    assert record.status == "recorded"
    assert record.outcome_recorded_at is None

    # Even after a decision and a re-score, still nothing.
    record_final_decision(record, "Go.", decided_by_user_id=owner.id)
    create_or_refresh_record(owner, "o-auto")
    assert DecisionRecord.query.get(record.id).outcomes == []


def test_completion_does_not_imply_success(client, app, db, loop_cast):
    """objective_met is only ever what a person said it was."""
    owner, record = loop_cast["owner"], loop_cast["record"]

    client.post(f"{BASE}/{record.id}/outcomes", headers=_headers(app, owner),
                json={"summary": "Rollout finished."})
    outcome = latest_outcome(DecisionRecord.query.get(record.id))
    assert outcome["objective_met"] is None
    assert outcome["status"] is None


def test_invalid_outcome_status_is_rejected(client, app, loop_cast):
    owner, record = loop_cast["owner"], loop_cast["record"]
    resp = client.post(f"{BASE}/{record.id}/outcomes", headers=_headers(app, owner),
                       json={"summary": "x", "status": "great_success"})
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "invalid_outcome"


def test_outcome_captures_expected_versus_observed_and_metrics(client, app, db, loop_cast):
    owner, record = loop_cast["owner"], loop_cast["record"]

    client.post(f"{BASE}/{record.id}/outcomes", headers=_headers(app, owner), json={
        "summary": "Below plan.",
        "expected_result": "12% cost reduction",
        "observed_result": "4% cost reduction",
        "metrics": [{"label": "Cost reduction", "value": "4", "expected": "12", "unit": "%"}],
        "objective_met": False,
    })

    outcome = latest_outcome(DecisionRecord.query.get(record.id))
    assert outcome["expected_result"] == "12% cost reduction"
    assert outcome["observed_result"] == "4% cost reduction"
    assert outcome["metrics"][0]["label"] == "Cost reduction"
    assert outcome["objective_met"] is False


# ── D / E / F / G. permissions ───────────────────────────────────────────────

def test_viewer_cannot_add_an_outcome(client, app, db, loop_cast):
    """The endpoint used the READ gate before this phase."""
    viewer, record = loop_cast["viewer"], loop_cast["record"]

    resp = client.post(f"{BASE}/{record.id}/outcomes", headers=_headers(app, viewer),
                       json={"summary": "Viewer says it went well"})
    assert resp.status_code == 403
    assert DecisionRecord.query.get(record.id).outcomes == []


def test_viewer_cannot_add_a_lesson(client, app, db, loop_cast):
    viewer, record = loop_cast["viewer"], loop_cast["record"]
    resp = client.post(f"{BASE}/{record.id}/lessons", headers=_headers(app, viewer),
                       json={"lesson": "Viewer lesson"})
    assert resp.status_code == 403
    assert DecisionRecord.query.get(record.id).lessons_learned == []


def test_viewer_can_read_outcomes_and_lessons(client, app, db, loop_cast):
    owner, viewer, record = loop_cast["owner"], loop_cast["viewer"], loop_cast["record"]
    client.post(f"{BASE}/{record.id}/outcomes", headers=_headers(app, owner),
                json={"summary": "It worked."})
    client.post(f"{BASE}/{record.id}/lessons", headers=_headers(app, owner),
                json={"lesson": "Start earlier."})

    resp = client.get(f"{BASE}/{record.id}", headers=_headers(app, viewer))
    assert resp.status_code == 200
    body = resp.get_json()["record"]
    assert body["outcomes"][0]["summary"] == "It worked."
    assert body["lessons_learned"][0]["lesson"] == "Start earlier."


def test_outsider_cannot_discover_or_add(client, app, db, loop_cast):
    outsider, record = loop_cast["outsider"], loop_cast["record"]

    assert client.get(f"{BASE}/{record.id}", headers=_headers(app, outsider)).status_code == 404
    resp = client.post(f"{BASE}/{record.id}/outcomes", headers=_headers(app, outsider),
                       json={"summary": "intrusion"})
    assert resp.status_code == 404
    assert DecisionRecord.query.get(record.id).outcomes == []


def test_private_outcomes_stay_private(client, app, db, team_setup):
    org, owner, editor = team_setup["org"], team_setup["owner"], team_setup["editor"]
    private = _decided_record(db, org, owner, "o-priv", "Confidential restructure",
                              visibility="private")
    client.post(f"{BASE}/{private.id}/outcomes", headers=_headers(app, owner),
                json={"summary": "Twelve roles removed."})

    assert client.get(f"{BASE}/{private.id}", headers=_headers(app, editor)).status_code == 404
    listing = client.get(f"{BASE}?limit=50", headers=_headers(app, editor))
    assert "Twelve roles removed" not in listing.get_data(as_text=True)


def test_collaborator_sees_the_same_canonical_outcome(client, app, db, loop_cast):
    owner, editor, record = loop_cast["owner"], loop_cast["editor"], loop_cast["record"]
    client.post(f"{BASE}/{record.id}/outcomes", headers=_headers(app, owner),
                json={"summary": "Shared observation."})

    resp = client.get(f"{BASE}/{record.id}", headers=_headers(app, editor))
    assert resp.get_json()["record"]["outcomes"][0]["summary"] == "Shared observation."


def test_adding_an_outcome_creates_no_duplicate_record(client, app, db, loop_cast):
    owner, record = loop_cast["owner"], loop_cast["record"]
    before = DecisionRecord.query.count()

    client.post(f"{BASE}/{record.id}/outcomes", headers=_headers(app, owner),
                json={"summary": "One."})
    client.post(f"{BASE}/{record.id}/lessons", headers=_headers(app, owner),
                json={"lesson": "Two."})

    assert DecisionRecord.query.count() == before
    assert DecisionRecord.query.filter_by(thread_id="o-thread").count() == 1


# ── I / J / K / L. lessons ───────────────────────────────────────────────────

def test_a_lesson_can_be_added_to_a_decided_record(client, app, db, loop_cast):
    owner, record = loop_cast["owner"], loop_cast["record"]
    resp = client.post(f"{BASE}/{record.id}/lessons", headers=_headers(app, owner),
                       json={"lesson": "Vendor transitions need procurement earlier."})
    assert resp.status_code == 201

    lesson = DecisionRecord.query.get(record.id).lessons_learned[0]
    assert lesson["lesson"] == "Vendor transitions need procurement earlier."
    assert lesson["recorded_by_user_id"] == owner.id
    assert lesson["recorded_by_name"]
    assert lesson["recorded_at"]
    assert lesson["id"].startswith("les_")


def test_multiple_lessons_never_overwrite_each_other(client, app, db, loop_cast):
    """J. The failure this phase must not have."""
    owner, record = loop_cast["owner"], loop_cast["record"]

    for text in ("Involve procurement earlier.", "Pilot before rollout.", "Budget 20% contingency."):
        client.post(f"{BASE}/{record.id}/lessons", headers=_headers(app, owner),
                    json={"lesson": text})

    lessons = DecisionRecord.query.get(record.id).lessons_learned
    assert [l["lesson"] for l in lessons] == [
        "Involve procurement earlier.", "Pilot before rollout.", "Budget 20% contingency.",
    ]
    assert len({l["id"] for l in lessons}) == 3


def test_a_lesson_may_cite_an_outcome_it_came_from(client, app, db, loop_cast):
    owner, record = loop_cast["owner"], loop_cast["record"]
    client.post(f"{BASE}/{record.id}/outcomes", headers=_headers(app, owner),
                json={"summary": "Late and over budget."})
    outcome_id = latest_outcome(DecisionRecord.query.get(record.id))["id"]

    resp = client.post(f"{BASE}/{record.id}/lessons", headers=_headers(app, owner),
                       json={"lesson": "Contingency budgets.", "outcome_id": outcome_id})
    assert resp.status_code == 201
    assert DecisionRecord.query.get(record.id).lessons_learned[0]["outcome_id"] == outcome_id


def test_a_lesson_cannot_cite_a_foreign_outcome(client, app, db, loop_cast):
    owner, record = loop_cast["owner"], loop_cast["record"]
    resp = client.post(f"{BASE}/{record.id}/lessons", headers=_headers(app, owner),
                       json={"lesson": "x", "outcome_id": "out_doesnotexist"})
    assert resp.status_code == 400
    assert resp.get_json()["code"] == "invalid_lesson"


def test_the_ai_recommendation_never_becomes_a_lesson(db, loop_cast):
    """L. Only a person's submission lands in lessons_learned."""
    owner, record = loop_cast["owner"], loop_cast["record"]
    recommendation = record.record["recommendation"]
    assert recommendation

    create_or_refresh_record(owner, "o-thread")

    stored = DecisionRecord.query.get(record.id)
    assert stored.lessons_learned == []
    assert all(recommendation not in str(l) for l in stored.lessons_learned)


def test_outcome_and_lesson_stay_structurally_separate(client, app, db, loop_cast):
    """Observation and judgement are different columns, not one blob."""
    owner, record = loop_cast["owner"], loop_cast["record"]
    client.post(f"{BASE}/{record.id}/outcomes", headers=_headers(app, owner),
                json={"summary": "Launch completed six weeks late."})
    client.post(f"{BASE}/{record.id}/lessons", headers=_headers(app, owner),
                json={"lesson": "Vendor transitions need procurement first."})

    stored = DecisionRecord.query.get(record.id)
    assert len(stored.outcomes) == 1 and len(stored.lessons_learned) == 1
    assert "procurement" not in stored.outcomes[0]["summary"]
    assert "six weeks late" not in stored.lessons_learned[0]["lesson"]


# ── 9. observations accumulate, history is not destroyed ─────────────────────

def test_a_later_observation_does_not_erase_an_earlier_one(client, app, db, loop_cast):
    owner, record = loop_cast["owner"], loop_cast["record"]

    client.post(f"{BASE}/{record.id}/outcomes", headers=_headers(app, owner),
                json={"summary": "Too early to tell.", "status": "too_early"})
    client.post(f"{BASE}/{record.id}/outcomes", headers=_headers(app, owner),
                json={"summary": "Six months on, target met.", "status": "achieved"})

    outcomes = DecisionRecord.query.get(record.id).outcomes
    assert len(outcomes) == 2
    assert outcomes[0]["status"] == "too_early"
    assert latest_outcome(DecisionRecord.query.get(record.id))["status"] == "achieved"


# ── M / N. supersession ──────────────────────────────────────────────────────

def test_a_superseded_record_keeps_its_own_outcome_and_lessons(client, app, db, loop_cast):
    org, owner, first = loop_cast["org"], loop_cast["owner"], loop_cast["record"]
    client.post(f"{BASE}/{first.id}/outcomes", headers=_headers(app, owner),
                json={"summary": "First attempt underperformed."})
    client.post(f"{BASE}/{first.id}/lessons", headers=_headers(app, owner),
                json={"lesson": "Scope creep killed the timeline."})

    second = _decided_record(db, org, owner, "o-thread-2", "Warehouse v2")
    supersede_record(second, first, owner)

    stored = DecisionRecord.query.get(first.id)
    assert current_state(stored) == "superseded"
    assert stored.outcomes[0]["summary"] == "First attempt underperformed."
    assert stored.lessons_learned[0]["lesson"] == "Scope creep killed the timeline."


def test_the_successor_inherits_nothing(client, app, db, loop_cast):
    """N. Lessons never migrate between decisions on their own."""
    org, owner, first = loop_cast["org"], loop_cast["owner"], loop_cast["record"]
    client.post(f"{BASE}/{first.id}/outcomes", headers=_headers(app, owner),
                json={"summary": "Underperformed."})
    client.post(f"{BASE}/{first.id}/lessons", headers=_headers(app, owner),
                json={"lesson": "Scope creep."})

    second = _decided_record(db, org, owner, "o-thread-3", "Warehouse v3")
    supersede_record(second, first, owner)

    fresh = DecisionRecord.query.get(second.id)
    assert fresh.outcomes == []
    assert fresh.lessons_learned == []


# ── O. retrieval summary ─────────────────────────────────────────────────────

def test_summary_reports_loop_state_without_loading_it(client, app, db, loop_cast):
    owner, record = loop_cast["owner"], loop_cast["record"]

    before = summarize(DecisionRecord.query.get(record.id))
    assert before["outcome"]["recorded"] is False
    assert before["lesson_count"] == 0
    assert before["has_lessons"] is False

    client.post(f"{BASE}/{record.id}/outcomes", headers=_headers(app, owner),
                json={"summary": "Delivered late.", "status": "partially_achieved",
                      "objective_met": False})
    client.post(f"{BASE}/{record.id}/lessons", headers=_headers(app, owner),
                json={"lesson": "Start procurement earlier."})

    after = summarize(DecisionRecord.query.get(record.id))
    assert after["outcome"]["recorded"] is True
    assert after["outcome"]["status"] == "partially_achieved"
    assert after["outcome"]["objective_met"] is False
    assert after["outcome"]["observation_count"] == 1
    assert after["lesson_count"] == 1
    assert after["has_lessons"] is True

    # Presence and status only -- the text itself is not in the summary.
    assert "Delivered late." not in str(after)
    assert "Start procurement earlier." not in str(after)


def test_retrieval_can_filter_on_loop_state(client, app, db, loop_cast):
    org, owner, record = loop_cast["org"], loop_cast["owner"], loop_cast["record"]
    _decided_record(db, org, owner, "o-nolesson", "Warehouse sidebar")

    client.post(f"{BASE}/{record.id}/outcomes", headers=_headers(app, owner),
                json={"summary": "Done."})

    with_outcome = {r["id"] for r in search(owner, "warehouse", has_outcome=True)}
    without = {r["id"] for r in search(owner, "warehouse", has_outcome=False)}

    assert record.id in with_outcome
    assert record.id not in without
    assert with_outcome.isdisjoint(without)


# ── P / Q. solo users and retention ──────────────────────────────────────────

def test_solo_user_can_close_the_loop(client, app, db):
    solo = _mk_user(db, "o-solo@example.test", plan="free")
    org = _mk_org(db, solo, name="OSolo", plan="free")
    record = _decided_record(db, org, solo, "o-solo-thread", "Solo pricing",
                             visibility="private")

    assert client.post(f"{BASE}/{record.id}/outcomes", headers=_headers(app, solo),
                       json={"summary": "Revenue up 6%."}).status_code == 201
    assert client.post(f"{BASE}/{record.id}/lessons", headers=_headers(app, solo),
                       json={"lesson": "Raise prices sooner."}).status_code == 201

    stored = DecisionRecord.query.get(record.id)
    assert len(stored.outcomes) == 1 and len(stored.lessons_learned) == 1


def test_organizational_learning_survives_the_author_being_removed(client, app, db, loop_cast):
    """Q. The retention reason this phase changed the FK.

    Outcomes and lessons cannot be re-derived from anything, so they must not
    cascade away with the person who typed them.
    """
    org, owner, editor, record = (
        loop_cast["org"], loop_cast["owner"], loop_cast["editor"], loop_cast["record"]
    )
    client.post(f"{BASE}/{record.id}/outcomes", headers=_headers(app, editor),
                json={"summary": "Delivered, over budget."})
    client.post(f"{BASE}/{record.id}/lessons", headers=_headers(app, editor),
                json={"lesson": "Budget contingency next time."})

    # Simulate departure at the level the ownership model supports: the
    # attribution link goes away, the organization's knowledge does not.
    stored = DecisionRecord.query.get(record.id)
    stored.user_id = None
    db.session.commit()

    survivor = DecisionRecord.query.get(record.id)
    assert survivor is not None
    assert survivor.organization_id == org.id
    assert survivor.outcomes[0]["summary"] == "Delivered, over budget."
    assert survivor.lessons_learned[0]["lesson"] == "Budget contingency next time."
    # Attribution survives as a name snapshot even with no user row linked.
    assert survivor.outcomes[0]["recorded_by_name"]
    assert survivor.record["attribution"].get("created_by_name")


def test_outcome_statuses_are_a_closed_vocabulary():
    assert "achieved" in OUTCOME_STATUSES
    assert "partially_achieved" in OUTCOME_STATUSES
    assert "too_early" in OUTCOME_STATUSES
