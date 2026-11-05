from datetime import datetime

from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from app.models import Organization, OrganizationMember, User
from app.models_decision_record import DecisionRecord, OptionDecision


def _user(db, email, name):
    user = User(
        email=email, name=name,
        password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
        subscription_plan="free", credits_remaining=100, seat_limit=1, max_seats=1,
    )
    db.session.add(user)
    db.session.flush()
    return user


def _organization(db, owner, *members):
    org = Organization(name=f"{owner.name} Org", owner_user_id=owner.id, plan_key="free")
    db.session.add(org)
    db.session.flush()
    for user, role in ((owner, "owner"), *members):
        db.session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role, status="active"))
        user.active_organization_id = org.id
    db.session.flush()
    return org


def _record(db, org, owner, thread_id, *, status="recorded", visibility="private", score=80):
    row = DecisionRecord(
        organization_id=org.id, user_id=owner.id, thread_id=thread_id,
        title=f"Decision {thread_id}", status=status,
        record={
            "source": {"visibility": visibility, "shared_with_user_ids": []},
            "scorecards": [{
                "name": "Option A", "jaspen_score": score,
                "assumptions": ["Demand holds"],
                "gates": [{"key": "approval", "label": "Approval", "status": "unknown"}],
                "evidence_profile": {"criteria": [{"key": "cost", "label": "Cost evidence", "confidence": "assumed", "evidenced": False}]},
            }],
        },
    )
    db.session.add(row)
    db.session.flush()
    return row


def _headers(app, user):
    with app.app_context():
        token = create_access_token(identity=str(user.id))
    return {"Authorization": f"Bearer {token}"}


def test_admin_can_switch_organization_and_mine_without_bypassing_record_visibility(client, db, app):
    owner = _user(db, "owner@example.com", "Owner")
    member = _user(db, "member@example.com", "Member")
    org = _organization(db, owner, (member, "creator"))
    own = _record(db, org, owner, "owner-record", visibility="team")
    shared = _record(db, org, member, "member-shared", visibility="team")
    _record(db, org, member, "member-private", visibility="private")
    own.record = {**own.record, "execution_plan": {"tasks": [{"id": "t1", "status": "in_progress"}]}}
    shared.record = {
        **shared.record,
        "decision_kit": "rfp_vendor_selection",
        "scorecards": [{
            **shared.record["scorecards"][0],
            "gates": [{"key": "approval", "label": "Approval", "status": "fail"}],
        }],
    }
    shared.outcomes = [{"summary": "Adoption reached the recorded target.", "recorded_at": "2026-11-03T10:00:00"}]
    shared.lessons_learned = [{"lesson": "Confirm ownership before rollout.", "recorded_at": "2026-11-04T10:00:00"}]
    shared.tags = ["procurement"]
    shared.decision_type = "vendor"
    for record, name in ((own, "Owner choice"), (shared, "Member choice")):
        db.session.add(OptionDecision(
            decision_record_id=record.id, option_key="option-a", option_name=name,
            final_decision=f"Proceed with {name}", decided_by_user_id=record.user_id,
            decided_at=datetime(2026, 11, 1),
        ))
        record.status = "decided"
    db.session.commit()

    org_payload = client.get("/api/v1/insights/overview?scope=organization", headers=_headers(app, owner)).get_json()
    assert org_payload["scope"] == "organization"
    assert org_payload["can_manage"] is True
    assert org_payload["can_view_organization"] is True
    assert org_payload["metrics"]["decision_records"] == 2
    assert {item["chosen_option"] for item in org_payload["decisions"]} == {"Owner choice", "Member choice"}
    assert {item["name"] for item in org_payload["activity_by_member"]} == {"Owner", "Member"}
    assert org_payload["open_items"][0]["unresolved"]["gates"][0]["label"] == "Approval"
    assert org_payload["open_items"][0]["unresolved"]["assumptions"] == []
    assert org_payload["metrics"]["in_progress"] == 0
    assert org_payload["metrics"]["needs_attention"] == 1
    assert org_payload["learning"]["outcomes"][0]["text"] == "Adoption reached the recorded target."
    assert org_payload["learning"]["lessons"][0]["text"] == "Confirm ownership before rollout."
    assert org_payload["progress"]["plans_in_execution"][0]["tasks_total"] == 1
    assert len(org_payload["rows"]) == 2
    shared_row = next(item for item in org_payload["rows"] if item["thread_id"] == "member-shared")
    assert shared_row["owner"] == {"id": str(member.id), "name": "Member"}
    assert shared_row["decision_type"] == "vendor"
    assert shared_row["decision_kit"] == "rfp_vendor_selection"
    assert shared_row["chosen_options"] == ["Member choice"]
    assert shared_row["top_option_score"] == 80
    assert shared_row["gaps"]["failed_gates"] == 1
    assert shared_row["lesson_count"] == 1
    assert shared_row["outcome_count"] == 1
    assert shared_row["tags"] == ["procurement"]
    assert set(org_payload["facets"]["types_kits"]) == {"rfp_vendor_selection", "vendor"}
    assert org_payload["facets"]["tags"] == ["procurement"]

    mine_payload = client.get("/api/v1/insights/overview?scope=mine", headers=_headers(app, owner)).get_json()
    assert mine_payload["scope"] == "mine"
    assert mine_payload["metrics"]["decision_records"] == 1
    assert mine_payload["activity_by_member"] == []


def test_non_admin_org_request_falls_back_to_mine_and_cross_org_is_isolated(client, db, app):
    owner = _user(db, "owner2@example.com", "Owner")
    member = _user(db, "member2@example.com", "Member")
    outsider = _user(db, "outside@example.com", "Outside")
    org = _organization(db, owner, (member, "creator"))
    other_org = _organization(db, outsider)
    _record(db, org, owner, "owner-team", visibility="team")
    _record(db, org, member, "member-own", visibility="team")
    _record(db, other_org, outsider, "outside", visibility="team")
    db.session.commit()

    response = client.get("/api/v1/insights/overview?scope=organization", headers=_headers(app, member))
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["requested_scope"] == "organization"
    assert payload["scope"] == "mine"
    assert payload["can_manage"] is False
    assert payload["can_view_organization"] is False
    assert payload["metrics"]["decision_records"] == 1
    assert payload["open_items"][0]["thread_id"] == "member-own"


def test_multi_member_org_admin_can_view_organization_scope(client, db, app):
    owner = _user(db, "scope-owner@example.com", "Scope Owner")
    admin = _user(db, "scope-admin@example.com", "Scope Admin")
    creator = _user(db, "scope-creator@example.com", "Scope Creator")
    org = _organization(db, owner, (admin, "admin"), (creator, "creator"))
    _record(db, org, admin, "admin-own", visibility="team")
    _record(db, org, creator, "creator-team", visibility="team")
    db.session.commit()

    payload = client.get(
        "/api/v1/insights/overview?scope=organization", headers=_headers(app, admin)
    ).get_json()
    assert payload["scope"] == "organization"
    assert payload["can_view_organization"] is True
    assert {row["thread_id"] for row in payload["rows"]} == {"admin-own", "creator-team"}


def test_scored_record_is_not_a_decision_and_results_are_not_truncated(client, db, app):
    owner = _user(db, "volume@example.com", "Volume Owner")
    org = _organization(db, owner)
    for index in range(1201):
        _record(db, org, owner, f"scored-{index}", score=70 + (index % 10))
    decided = _record(db, org, owner, "decided", status="decided")
    _record(db, org, owner, "archived", status="archived")
    db.session.add(OptionDecision(
        decision_record_id=decided.id, option_key="chosen", option_name="Chosen option",
        final_decision="Proceed", decided_by_user_id=owner.id,
        decided_at=datetime(2026, 11, 2),
    ))
    db.session.commit()

    payload = client.get("/api/v1/insights/overview?scope=mine", headers=_headers(app, owner)).get_json()
    assert payload["metrics"]["decision_records"] == 1203
    assert payload["metrics"]["decisions_made"] == 1
    assert payload["metrics"]["in_progress"] == 1201
    assert payload["metrics"]["needs_attention"] == 0
    assert len(payload["open_items"]) == 1201
    assert payload["limits"] == {"records_capped": False, "items_capped": False}


def test_superseded_record_is_counted_once(client, db, app):
    owner = _user(db, "superseded@example.com", "Supersession Owner")
    org = _organization(db, owner)
    prior = _record(db, org, owner, "prior", status="decided")
    successor = _record(db, org, owner, "successor", status="decided")
    successor.supersedes_id = prior.id
    for record, option_name in ((prior, "Old choice"), (successor, "Current choice")):
        db.session.add(OptionDecision(
            decision_record_id=record.id, option_key="choice", option_name=option_name,
            final_decision=f"Proceed with {option_name}", decided_by_user_id=owner.id,
            decided_at=datetime(2026, 11, 2),
        ))
    db.session.commit()

    payload = client.get("/api/v1/insights/overview?scope=mine", headers=_headers(app, owner)).get_json()
    assert payload["metrics"]["decision_records"] == 1
    assert payload["metrics"]["decisions_made"] == 1
    assert [item["chosen_option"] for item in payload["decisions"]] == ["Current choice"]
    assert [item["thread_id"] for item in payload["rows"]] == ["successor"]


def test_attention_deduplicates_assumption_and_missing_evidence_for_same_criterion(client, db, app):
    owner = _user(db, "dedup@example.com", "Dedup Owner")
    org = _organization(db, owner)
    record = _record(db, org, owner, "dedup")
    record.record = {
        **record.record,
        "scorecards": [{
            "name": "Option A",
            "gates": [],
            "assumptions": [{"criterion_key": "cost", "assumption": "Cost remains in budget"}],
            "evidence_profile": {"criteria": [
                {"key": "cost", "label": "Cost evidence", "confidence": "assumed", "evidenced": False},
                {"key": "timing", "label": "Timing evidence", "confidence": "assumed", "evidenced": False},
            ]},
        }],
    }
    db.session.commit()

    payload = client.get("/api/v1/insights/overview?scope=mine", headers=_headers(app, owner)).get_json()
    unresolved = payload["open_items"][0]["unresolved"]
    assert [item["label"] for item in unresolved["assumptions"]] == ["Cost remains in budget"]
    assert [item["label"] for item in unresolved["missing_evidence"]] == ["Timing evidence"]


def test_individual_account_gets_an_org_and_empty_overview(client, db, app, test_user, auth_headers):
    response = client.get("/api/v1/insights/overview?scope=organization", headers=auth_headers)
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["organization"]["id"]
    assert payload["scope"] == "mine"
    assert payload["requested_scope"] == "organization"
    assert payload["can_view_organization"] is False
    assert payload["metrics"]["decision_records"] == 0
    assert payload["decisions"] == []

