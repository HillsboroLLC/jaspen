from datetime import datetime, timedelta

from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from app.models import Organization, OrganizationMember, User, UserSession
from app.models_decision_record import DecisionRecord, DecisionSignal, OptionDecision


def _user(db, email, name):
    user = User(email=email, name=name, password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"), subscription_plan="free", credits_remaining=100, seat_limit=1, max_seats=1)
    db.session.add(user); db.session.flush(); return user


def _organization(db, owner, *members, plan="free"):
    org = Organization(name=f"{owner.name} Org", owner_user_id=owner.id, plan_key=plan)
    db.session.add(org); db.session.flush()
    for user, role in ((owner, "owner"), *members):
        db.session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role, status="active")); user.active_organization_id = org.id
    db.session.flush(); return org


def _record(db, org, owner, thread_id, cards, *, visibility="private", kit="general"):
    row = DecisionRecord(organization_id=org.id, user_id=owner.id, thread_id=thread_id, title=f"Decision {thread_id}", status="recorded", decision_type=kit, record={"source": {"visibility": visibility, "shared_with_user_ids": []}, "decision_kit": kit, "scorecards": cards})
    db.session.add(row); db.session.flush(); return row


def _card(key, *, card_id=None, first="2026-10-01T10:00:00", score=80, evidence=60, gates=None, criteria=None, attributes=None):
    return {"id": card_id or f"card-{key}", "option_key": key, "name": key.replace("-", " ").title(), "first_scored_at": first, "jaspen_score": score, "score_category": "Strong", "evidence_profile": {"evidence_backed_pct": evidence, "criteria": criteria or []}, "gates": gates or [], "attributes": attributes or {}}


def _decision(db, record, key, disposition, *, at=None, source="conversation", outcomes=None, lessons=None):
    row = OptionDecision(decision_record_id=record.id, option_key=key, option_name=key.replace("-", " ").title(), final_decision=disposition, disposition=disposition, source=source, decided_by_user_id=record.user_id, decided_at=at or datetime(2026, 10, 2, 10), user_quote=f"I choose {key}", outcomes=outcomes or [], lessons_learned=lessons or [])
    db.session.add(row); return row


def _session(db, user, org, thread_id, plans):
    row = UserSession(user_id=user.id, organization_id=org.id, session_id=thread_id, name="Decision", scenarios_json={"wbs_by_scorecard": plans}, visibility="private")
    db.session.add(row); return row


def _headers(app, user):
    with app.app_context(): token = create_access_token(identity=str(user.id))
    return {"Authorization": f"Bearer {token}"}


def _get(client, app, user, query="scope=mine"):
    response = client.get(f"/api/v1/insights/overview?{query}", headers=_headers(app, user))
    assert response.status_code == 200
    return response.get_json()


def test_option_states_reconcile_across_multi_option_rescore_and_filters(client, db, app):
    owner = _user(db, "reconcile@example.com", "Owner"); org = _organization(db, owner)
    cards = [_card("alpha", card_id="alpha-v1", score=70), _card("alpha", card_id="alpha-v2", score=85), _card("beta", first="2026-10-02T10:00:00"), _card("gamma", first="2026-10-03T10:00:00")]
    record = _record(db, org, owner, "multi", cards); _decision(db, record, "alpha", "pursue"); _decision(db, record, "beta", "not_pursue"); db.session.commit()
    payload = _get(client, app, owner); activity = payload["activity"]
    assert activity["reconciles"] is True and activity["total_scored"]["value"] == 3
    assert [activity[key]["value"] for key in ("pursued", "not_pursued", "open", "archived")] == [1, 1, 1, 0]
    assert {row["option_key"] for row in payload["register"]["rows"]} == {"alpha", "beta", "gamma"}
    pursued = _get(client, app, owner, "scope=mine&state=pursued")
    assert pursued["activity"]["total_scored"]["value"] == 1 and pursued["activity"]["reconciles"] is True


def test_cohort_and_time_to_plan_use_option_dates(client, db, app):
    owner = _user(db, "cohort@example.com", "Owner"); org = _organization(db, owner); now = datetime.utcnow().replace(microsecond=0); first = now - timedelta(days=5)
    record = _record(db, org, owner, "cohort", [_card("alpha", card_id="alpha-card", first=first.isoformat())]); _decision(db, record, "alpha", "pursue", at=first + timedelta(hours=3))
    _session(db, owner, org, "cohort", {"alpha-card": {"created_at": (first + timedelta(hours=2)).isoformat(), "tasks": [], "decision_basis": {"scorecard_id": "alpha-card", "captured_at": first.isoformat(), "jaspen_score": 80, "evidence_backed_pct": 60}}}); db.session.commit()
    payload = _get(client, app, owner, "scope=mine&days=14"); metric = payload["activity"]["average_time_to_plan_hours"]
    assert metric["value"] == 2 and metric["coverage"] == 1
    assert payload["activity"]["flow"][0]["date"] == (first.date() - timedelta(days=first.weekday())).isoformat()
    assert _get(client, app, owner, "scope=mine&days=1")["activity"]["total_scored"]["value"] == 0


def test_plan_rows_use_option_decision_names_not_a_migrated_parent_title(client, db, app):
    owner = _user(db, "migrated-plans@example.com", "Owner"); org = _organization(db, owner)
    options = [
        ("adams-county-road-resurfacing", "adams-card"),
        ("boulder-stormwater-upgrade", "boulder-card"),
        ("denver-bike-lane-package", "denver-card"),
    ]
    record = _record(db, org, owner, "migrated-plans", [
        _card(key, card_id=card_id) for key, card_id in options
    ])
    record.title = "Denver Bike Lane Package"
    plans = {}
    for key, card_id in options:
        _decision(db, record, key, "pursue")
        plans[card_id] = {
            "created_at": "2026-10-02T12:00:00",
            "tasks": [],
            "decision_basis": {"scorecard_id": card_id},
        }
    _session(db, owner, org, "migrated-plans", plans)
    db.session.commit()

    rows = _get(client, app, owner)["activity"]["plans"]

    assert {row["decision_name"] for row in rows} == {
        "Adams County Road Resurfacing",
        "Boulder Stormwater Upgrade",
        "Denver Bike Lane Package",
    }
    assert {row["decision_title"] for row in rows} == {"Denver Bike Lane Package"}


def test_single_plan_name_falls_back_to_its_associated_scorecard(client, db, app):
    owner = _user(db, "single-plan@example.com", "Owner"); org = _organization(db, owner)
    record = _record(db, org, owner, "single-plan", [
        _card("launch-alpha", card_id="launch-card"),
    ])
    decision = _decision(db, record, "launch-alpha", "pursue")
    decision.option_name = None
    _session(db, owner, org, "single-plan", {
        "launch-card": {
            "created_at": "2026-10-02T12:00:00",
            "tasks": [],
            "decision_basis": {"scorecard_id": "launch-card"},
        },
    })
    db.session.commit()

    row = _get(client, app, owner)["activity"]["plans"][0]

    assert row["decision_name"] == "Launch Alpha"
    assert row["option_key"] == "launch-alpha"


def test_attention_requires_stored_conditions_and_ignores_generated_dates(client, db, app):
    owner = _user(db, "attention@example.com", "Owner"); org = _organization(db, owner); due = (datetime.utcnow().date() + timedelta(days=7)).isoformat(); gates = [{"key": "security", "label": "Security", "status": "failed"}]
    rfp = _record(db, org, owner, "rfp", [_card("bid", card_id="bid-card", first=datetime.utcnow().isoformat(), gates=gates, attributes={"submission_due": {"value": due}})], kit="rfp_bid"); _decision(db, rfp, "bid", "pursue")
    _session(db, owner, org, "rfp", {"bid-card": {"created_at": datetime.utcnow().isoformat(), "tasks": [{"id": "generated", "due_date": "2000-01-01", "status": "open"}], "decision_basis": {"scorecard_id": "bid-card", "captured_at": datetime.utcnow().isoformat(), "gates": gates}}}); db.session.commit()
    triggers = _get(client, app, owner)["register"]["rows"][0]["triggers"]
    assert {item["kind"] for item in triggers} == {"decision_milestone_at_risk", "failed_required_check_without_task"}
    assert all(item["evidence"] and item["next_step_ref"] for item in triggers)


def test_committed_overdue_and_dependency_triggers_only(client, db, app):
    owner = _user(db, "tasks@example.com", "Owner"); org = _organization(db, owner)
    record = _record(db, org, owner, "tasks", [_card("alpha", card_id="alpha-card", first=datetime.utcnow().isoformat())]); _decision(db, record, "alpha", "pursue")
    tasks = [{"id": "late", "status": "open", "commitment": {"due_date": "2000-01-01"}}, {"id": "blocked", "status": "open", "depends_on": ["late"]}, {"id": "done", "status": "complete", "commitment": {"due_date": "2000-01-01"}}, {"id": "generated", "status": "open", "due_date": "2000-01-01"}]
    _session(db, owner, org, "tasks", {"alpha-card": {"created_at": datetime.utcnow().isoformat(), "tasks": tasks, "decision_basis": {"scorecard_id": "alpha-card", "captured_at": datetime.utcnow().isoformat()}}}); db.session.commit()
    kinds = [item["kind"] for item in _get(client, app, owner)["register"]["rows"][0]["triggers"]]
    assert kinds.count("committed_task_overdue") == 1 and kinds.count("blocked_by_overdue_commitment") == 1


def test_gap_stages_remain_separate_and_plan_completion_is_not_success(client, db, app):
    owner = _user(db, "gaps@example.com", "Owner"); org = _organization(db, owner); criteria = [{"key": "cost", "label": "Cost", "group": "viability", "evidenced": True}]
    record = _record(db, org, owner, "gaps", [_card("alpha", card_id="alpha-card", first=datetime.utcnow().isoformat(), criteria=criteria)]); _decision(db, record, "alpha", "pursue")
    basis = {"scorecard_id": "alpha-card", "captured_at": datetime.utcnow().isoformat(), "unevidenced_criteria": [{"key": "cost", "label": "Cost", "group": "viability"}]}; tasks = [{"id": "cost-task", "status": "complete", "lineage": {"ref": "cost"}}]
    _session(db, owner, org, "gaps", {"alpha-card": {"created_at": datetime.utcnow().isoformat(), "tasks": tasks, "decision_basis": basis}}); db.session.commit()
    payload = _get(client, app, owner); stages = payload["effectiveness"]["gap_follow_through"]
    assert stages == {"identified": 1, "task_created": 1, "task_completed": 1, "resolved": 1, "result": 0}
    assert payload["effectiveness"]["outcomes"]["implementation_complete"] == 1 and payload["effectiveness"]["outcomes"]["measured"] == 0
    recurring = payload["effectiveness"]["recurring_gaps"][0]
    assert recurring["key"] == "viability" and recurring["decisions_affected"] == recurring["decisions_total"] == 1


def test_review_due_and_stated_outcomes_are_separate_stages(client, db, app):
    owner = _user(db, "outcomes@example.com", "Owner"); org = _organization(db, owner)
    record = _record(db, org, owner, "outcomes", [_card("alpha", first=datetime.utcnow().isoformat())]); _decision(db, record, "alpha", "pursue", outcomes=[{"status": "achieved", "objective_met": True}], lessons=[{"lesson": "Start earlier"}])
    db.session.add(DecisionSignal(organization_id=org.id, attribution_user_id=owner.id, actor_user_id=owner.id, thread_id="outcomes", decision_record_id=record.id, option_key="alpha", kind="success_measure", content="Reach target", source="manual", structured={"review_by": "2000-01-01"})); db.session.commit()
    payload = _get(client, app, owner)
    assert not any(trigger["kind"] == "outcome_review_due" for trigger in payload["register"]["rows"][0]["triggers"])
    assert payload["effectiveness"]["outcomes"]["success_measure_captured"] == 1
    assert payload["effectiveness"]["outcomes"]["measured"] == payload["effectiveness"]["outcomes"]["met_expectation"] == 1


def test_scope_matrix_uses_plan_role_member_count_and_visibility(client, db, app):
    owner = _user(db, "scope-owner@example.com", "Owner"); owner.subscription_plan = "team"
    member = _user(db, "scope-member@example.com", "Member"); org = _organization(db, owner, plan="team")
    _record(db, org, owner, "solo", [_card("solo", first=datetime.utcnow().isoformat())]); db.session.commit()
    solo = _get(client, app, owner, "scope=organization"); assert solo["scope"] == "organization" and solo["show_scope_control"] is False
    db.session.add(OrganizationMember(organization_id=org.id, user_id=member.id, role="creator", status="active")); member.active_organization_id = org.id
    _record(db, org, member, "member-team", [_card("shared", first=datetime.utcnow().isoformat())], visibility="team"); _record(db, org, member, "member-private", [_card("private", first=datetime.utcnow().isoformat())], visibility="private"); db.session.commit()
    owner_payload = _get(client, app, owner, "scope=organization")
    assert owner_payload["show_scope_control"] is True and {row["thread_id"] for row in owner_payload["register"]["rows"]} == {"solo", "member-team"}
    member_payload = _get(client, app, member, "scope=organization"); assert member_payload["scope"] == "mine" and member_payload["show_scope_control"] is False
    free_owner = _user(db, "free@example.com", "Free"); free_org = _organization(db, free_owner, plan="free"); _record(db, free_org, free_owner, "free", [_card("free", first=datetime.utcnow().isoformat())]); db.session.commit()
    assert _get(client, app, free_owner, "scope=organization")["scope"] == "mine"


def test_missing_metrics_are_null_with_a_reason(client, db, app):
    owner = _user(db, "empty@example.com", "Empty"); _organization(db, owner); db.session.commit(); payload = _get(client, app, owner)
    assert payload["activity"]["average_time_to_plan_hours"]["value"] is None
    assert payload["activity"]["average_time_to_plan_hours"]["unavailable_reason"] == "no_plans"
    assert payload["effectiveness"]["evidence_at_commitment"]["value"] is None
    assert payload["effectiveness"]["evidence_at_commitment"]["unavailable_reason"] == "insufficient_months"


# ── Completion of phase 2 (Claude) ─────────────────────────────────────────


def _signal(db, org, owner, record, key, kind, content, structured=None, at=None, supersedes=None):
    row = DecisionSignal(organization_id=org.id, attribution_user_id=owner.id, actor_user_id=owner.id, thread_id=record.thread_id,
                         decision_record_id=record.id, option_key=key, kind=kind, content=content, source="conversation",
                         user_quote=content, structured=structured or {}, occurred_at=at or datetime.utcnow(), supersedes_id=supersedes)
    db.session.add(row); db.session.flush(); return row


def test_conditions_and_against_recommendation_are_markers_not_new_states(client, db, app):
    owner = _user(db, "cond@example.com", "Owner"); org = _organization(db, owner)
    record = _record(db, org, owner, "cond", [_card("alpha"), _card("beta")], kit="rfp_bid")
    row = _decision(db, record, "alpha", "pursue")
    row.override_info = {"override_of": "decline", "failed_check_labels": []}
    row.kit_verdict = {"verdict_key": "advance_with_conditions", "recommendation_snapshot": {"verdict_key": "decline", "label": "No-Bid"}}
    _decision(db, record, "beta", "not_pursue")
    first = _signal(db, org, owner, record, "alpha", "condition", "Bonding secured", {"status": "open", "due_by": "2000-01-01"})
    _signal(db, org, owner, record, "beta", "condition", "Price drops", {"status": "open", "due_by": "2000-01-01"})
    db.session.commit()
    payload = _get(client, app, owner)
    rows = {row["option_key"]: row for row in payload["register"]["rows"]}
    assert rows["alpha"]["state"] == "pursued"
    assert rows["alpha"]["conditions"][0]["status"] == "open"
    assert rows["alpha"]["against_recommendation"]["jaspen_recommendation"] == "No-Bid"
    # A not-pursued option's conditions no longer apply.
    assert rows["beta"]["conditions"] == [] and rows["beta"]["against_recommendation"] is None
    past_due = [t for t in rows["alpha"]["triggers"] if t["kind"] == "condition_past_due"]
    assert past_due and past_due[0]["evidence"]["signal_id"] == str(first.id)
    assert not [t for t in rows["beta"]["triggers"] if t["kind"] == "condition_past_due"]
    activity = payload["activity"]
    assert set(k for k in ("pursued", "not_pursued", "open", "archived")) <= set(activity) and activity["reconciles"] is True

    met = _signal(db, org, owner, record, "alpha", "condition", "Bonding secured", {"status": "met", "due_by": "2000-01-01"}, supersedes=str(first.id))
    db.session.commit()
    rows = {row["option_key"]: row for row in _get(client, app, owner)["register"]["rows"]}
    assert [c["status"] for c in rows["alpha"]["conditions"]] == ["met"]
    assert not [t for t in rows["alpha"]["triggers"] if t["kind"] == "condition_past_due"]
    assert met.id


def test_triggers_carry_facts_only_never_backend_prose(client, db, app):
    owner = _user(db, "prose@example.com", "Owner"); org = _organization(db, owner)
    soon = (datetime.utcnow() + timedelta(days=5)).date().isoformat()
    record = _record(db, org, owner, "prose", [_card("alpha", gates=[{"key": "surety", "label": "Surety", "status": "unknown"}])], kit="rfp_bid")
    _decision(db, record, "alpha", "pursue")
    _signal(db, org, owner, record, None, "deadline", "Bid due", {"date": soon})
    db.session.commit()
    row = _get(client, app, owner)["register"]["rows"][0]
    trigger = next(t for t in row["triggers"] if t["kind"] == "decision_milestone_at_risk")
    assert trigger["evidence"]["deadline"] == soon and trigger["evidence"]["window_days"] == 14
    assert all("condition" not in t for t in row["triggers"])


def test_outcomes_on_earlier_decision_versions_still_count(client, db, app):
    owner = _user(db, "versions@example.com", "Owner"); org = _organization(db, owner)
    record = _record(db, org, owner, "versions", [_card("alpha")])
    _decision(db, record, "alpha", "pursue", at=datetime(2026, 10, 1), outcomes=[{"status": "achieved", "objective_met": True}],
              lessons=[{"lesson": "Start earlier", "recorded_at": "2026-10-05T00:00:00"}])
    _decision(db, record, "alpha", "pursue", at=datetime(2026, 10, 9))
    db.session.commit()
    outcomes = _get(client, app, owner)["effectiveness"]["outcomes"]
    assert outcomes["measured"] == 1 and outcomes["measured_by_status"]["achieved"] == 1
    assert outcomes["lessons"] == 1 and outcomes["latest_lesson"]["lesson"] == "Start earlier"


def test_too_early_and_future_review_are_awaiting_measurement(client, db, app):
    owner = _user(db, "awaiting@example.com", "Owner"); org = _organization(db, owner)
    record = _record(db, org, owner, "awaiting", [_card("alpha"), _card("beta")])
    _decision(db, record, "alpha", "pursue", outcomes=[{"status": "too_early"}])
    _decision(db, record, "beta", "pursue")
    future = (datetime.utcnow() + timedelta(days=30)).date().isoformat()
    _signal(db, org, owner, record, "beta", "success_measure", "Reach 20 leads", {"review_by": future})
    db.session.commit()
    outcomes = _get(client, app, owner)["effectiveness"]["outcomes"]
    assert outcomes["awaiting_measurement"] == 2 and outcomes["measured"] == 0


def test_gap_resolved_by_ledger_event_and_before_plan_series(client, db, app):
    from app.models_challenge_event import ChallengeEvent

    owner = _user(db, "ledger@example.com", "Owner"); org = _organization(db, owner)
    basis = {"captured_at": "2026-10-03T00:00:00", "evidence_backed_pct": 40, "unevidenced_criteria": [{"key": "margin", "label": "Margin"}]}
    record = _record(db, org, owner, "ledger", [_card("alpha")])
    _decision(db, record, "alpha", "pursue")
    _session(db, owner, org, "ledger", {"card-alpha": {"created_at": "2026-10-03T12:00:00", "decision_basis": basis, "tasks": []}})
    db.session.add(ChallengeEvent(user_id=owner.id, thread_id="ledger", epoch=1, seq=1, occurred_at=datetime(2026, 10, 2), type="assumption_resolved",
                                  target_kind="criterion", target_id="margin", origin="test", dedupe_key="ledger-margin"))
    db.session.commit()
    payload = _get(client, app, owner)
    gap = payload["register"]["rows"][0]["gaps"][0]
    assert gap["resolved"] is True and gap["task_completed"] is False
    point = payload["effectiveness"]["evidence_at_commitment"]["points"][0]
    assert point["gaps_identified"] == 1 and point["gaps_resolved_before_plan_pct"] == 100.0


def test_summary_ranks_exception_then_pattern_with_at_most_three(client, db, app):
    owner = _user(db, "summary@example.com", "Owner"); org = _organization(db, owner)
    for index in range(3):
        record = _record(db, org, owner, f"sum-{index}", [_card(f"opt-{index}", evidence=30, gates=[{"key": "surety", "label": "Surety", "status": "fail"}])], kit="rfp_bid")
        _decision(db, record, f"opt-{index}", "pursue")
        _session(db, owner, org, f"sum-{index}", {f"card-opt-{index}": {"created_at": "2026-10-03T12:00:00", "tasks": [],
                 "decision_basis": {"captured_at": f"2026-0{7 + index}-01T00:00:00", "evidence_backed_pct": 30 + index * 10, "gates": [{"key": "surety", "label": "Surety", "status": "fail"}]}}})
    db.session.commit()
    summary = _get(client, app, owner)["summary"]
    assert len(summary) <= 3
    assert [finding["kind"] for finding in summary][0] == "exception"
    kinds = [finding["kind"] for finding in summary]
    assert kinds == sorted(kinds, key=["exception", "pattern", "follow_through", "improvement"].index)
