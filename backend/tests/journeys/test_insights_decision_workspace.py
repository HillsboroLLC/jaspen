"""Customer journey coverage for decision work flowing into Insights."""

from datetime import datetime

from app.models_decision_record import DecisionRecord, OptionDecision


def test_recorded_choice_and_lesson_appear_in_customer_insights(client, db, test_user, auth_headers):
    # First visit establishes the individual subscriber's active organization.
    first = client.get("/api/v1/insights/overview?scope=mine", headers=auth_headers)
    assert first.status_code == 200
    org_id = first.get_json()["organization"]["id"]

    record = DecisionRecord(
        user_id=test_user.id, organization_id=org_id, thread_id="journey-insights",
        title="Choose a launch approach", status="decided",
        record={"source": {"visibility": "private"}, "scorecards": [{
            "id": "pilot-card", "option_key": "pilot", "name": "Phased pilot",
            "first_scored_at": "2026-11-05T10:00:00", "jaspen_score": 82,
            "score_category": "Strong", "evidence_profile": {"evidence_backed_pct": 60},
        }]},
        outcomes=[{"summary": "The pilot reached its launch target.", "status": "achieved", "recorded_at": "2026-11-05T13:00:00"}],
        lessons_learned=[{"lesson": "Pilot evidence changed the rollout sequence.", "recorded_at": "2026-11-05T12:00:00"}],
    )
    db.session.add(record)
    db.session.flush()
    db.session.add(OptionDecision(
        decision_record_id=record.id, option_key="pilot", option_name="Phased pilot",
        final_decision="Proceed with the phased pilot", decided_by_user_id=test_user.id,
        disposition="pursue", source="manual",
        decided_at=datetime(2026, 11, 5, 11, 0, 0),
    ))
    db.session.commit()

    response = client.get("/api/v1/insights/overview?scope=mine", headers=auth_headers)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["activity"]["pursued"]["value"] == 1
    assert payload["register"]["rows"][0]["option_name"] == "Phased pilot"
    assert payload["register"]["rows"][0]["history"][0]["source"] == "manual"
    outcomes = payload["effectiveness"]["outcomes"]
    assert outcomes["outcomes_recorded"] == 1
    assert outcomes["lessons"] == 1
    assert outcomes["latest_lesson"]["lesson"] == "Pilot evidence changed the rollout sequence."
