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
    record = _record(db, org, owner, "outcomes", [_card("alpha", first=datetime.utcnow().isoformat())]); _decision(db, record, "alpha", "pursue", outcomes=[{"status": "measured", "objective_met": True}], lessons=[{"lesson": "Start earlier"}])
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
