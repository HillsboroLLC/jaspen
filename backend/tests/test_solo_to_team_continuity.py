"""Pre-merge hardening: solo -> team is an UPGRADE, not a replacement.

Every user's projects, Decision Records, outcomes, lessons and organizational
memory hang off their organization's id. If going multi-user minted a second
organization and repointed the user at it, every one of those would be stranded
in an org they can no longer reach -- silently, because retrieval is scoped to
the active organization. These tests pin the continuity invariant.
"""
import pytest

from app.billing_config import apply_plan_to_user
from app.decision_records import append_lesson, append_outcome, create_or_refresh_record
from app.models import Organization, OrganizationInvitation, OrganizationMember, UserSession
from app.models_decision_record import DecisionRecord
from app.orgs import ensure_default_organization_for_user, resolve_active_org_for_user

from tests.test_session_org_ownership import _headers, _mk_org, _mk_user
from tests.test_decision_record_pipeline import _seed_scored_project


def _upgrade(app, db, user, plan="team"):
    """Subscription change only -- exactly what billing does."""
    with app.app_context():
        from flask import current_app
        apply_plan_to_user(user, plan, current_app.config, reset_credits=False)
    db.session.commit()


def _solo_with_history(app, db, email="cont@example.test"):
    """A solo user who has actually used the product."""
    user = _mk_user(db, email, plan="free")
    org, _m = resolve_active_org_for_user(user)

    _seed_scored_project(db, org, user, session_id="cont-1",
                         visibility="private", name="Pricing model change")
    record, _ = create_or_refresh_record(user, "cont-1")
    from app.decision_records import record_final_decision
    record_final_decision(record, "We raised prices 8%.", decided_by_user_id=user.id)
    append_outcome(record, "Revenue up 6% in the first quarter.",
                   extra={"status": "achieved"}, actor=user)
    append_lesson(record, "Raise prices earlier next time.", actor=user)

    return user, org, record


# ── 1 / 2. the organization is upgraded, not replaced ────────────────────────

def test_solo_org_keeps_its_id_through_upgrade_and_team_creation(client, app, db):
    user, org, _record = _solo_with_history(app, db)
    original_id = org.id

    _upgrade(app, db, user)

    resp = client.post("/api/v1/teams", headers=_headers(app, user),
                       json={"name": "Acme Team"})
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()

    assert body["created"] is False
    assert body["reused_existing_organization"] is True
    assert body["organization"]["id"] == original_id, (
        "team creation replaced the user's organization"
    )


def test_team_creation_does_not_mint_a_second_owned_org(client, app, db):
    user, org, _record = _solo_with_history(app, db)
    _upgrade(app, db, user)

    for _ in range(3):
        client.post("/api/v1/teams", headers=_headers(app, user),
                    json={"name": "Acme Team"})

    owned = Organization.query.filter_by(owner_user_id=user.id).all()
    assert len(owned) == 1, f"user owns {len(owned)} organizations"
    assert owned[0].id == org.id
    assert user.active_organization_id == org.id


def test_naming_the_team_renames_the_existing_org_rather_than_replacing_it(client, app, db):
    user, org, _record = _solo_with_history(app, db)
    original_id = org.id
    _upgrade(app, db, user)

    client.post("/api/v1/teams", headers=_headers(app, user),
                json={"name": "Acme Team"})

    refreshed = Organization.query.get(original_id)
    assert refreshed is not None
    assert refreshed.name == "Acme Team"
    assert refreshed.id == original_id


# ── 3 / 4 / 5. everything stays attached ─────────────────────────────────────

def test_existing_project_stays_attached_to_the_same_org(client, app, db):
    user, org, _record = _solo_with_history(app, db)
    _upgrade(app, db, user)
    client.post("/api/v1/teams", headers=_headers(app, user), json={"name": "Acme Team"})

    row = UserSession.query.filter_by(session_id="cont-1").one()
    assert row.organization_id == org.id
    assert row.created_by_user_id == user.id


def test_existing_decision_record_stays_attached_to_the_same_org(client, app, db):
    user, org, record = _solo_with_history(app, db)
    _upgrade(app, db, user)
    client.post("/api/v1/teams", headers=_headers(app, user), json={"name": "Acme Team"})

    refreshed = DecisionRecord.query.get(record.id)
    assert refreshed.organization_id == org.id
    assert refreshed.user_id == user.id
    assert DecisionRecord.query.count() == 1


def test_outcomes_and_lessons_survive_the_upgrade(client, app, db):
    user, _org, record = _solo_with_history(app, db)
    _upgrade(app, db, user)
    client.post("/api/v1/teams", headers=_headers(app, user), json={"name": "Acme Team"})

    refreshed = DecisionRecord.query.get(record.id)
    assert refreshed.final_decision == "We raised prices 8%."
    assert refreshed.outcomes[0]["summary"] == "Revenue up 6% in the first quarter."
    assert refreshed.lessons_learned[0]["lesson"] == "Raise prices earlier next time."


def test_organizational_memory_still_finds_the_pre_upgrade_history(client, app, db):
    """The point of the whole invariant: memory keeps working across the upgrade."""
    from app.decision_retrieval import search

    user, _org, record = _solo_with_history(app, db)
    _upgrade(app, db, user)
    client.post("/api/v1/teams", headers=_headers(app, user), json={"name": "Acme Team"})

    results = search(user, "pricing", current="all")
    assert [r["id"] for r in results] == [record.id], (
        "pre-upgrade organizational memory became unreachable"
    )


# ── 6. the invitation lands on the existing org ──────────────────────────────

def test_the_first_invitation_expands_the_existing_organization(client, app, db):
    user, org, _record = _solo_with_history(app, db)
    _upgrade(app, db, user)

    created = client.post("/api/v1/teams", headers=_headers(app, user),
                          json={"name": "Acme Team"}).get_json()
    org_id = created["organization"]["id"]

    invite = client.post(f"/api/v1/teams/{org_id}/invite", headers=_headers(app, user),
                         json={"email": "colleague@example.test", "role": "collaborator"})
    assert invite.status_code == 201, invite.get_json()

    row = OrganizationInvitation.query.filter_by(email="colleague@example.test").one()
    assert row.organization_id == org.id
    assert Organization.query.count() == 1


def test_the_ui_flow_invites_against_the_solo_org_without_calling_create(client, app, db):
    """The path the shipped frontend actually takes: summary -> invite."""
    user, org, _record = _solo_with_history(app, db)
    _upgrade(app, db, user)

    summary = client.get("/api/v1/team/summary", headers=_headers(app, user))
    active = summary.get_json()["organization"]
    assert active["id"] == org.id
    assert active["plan_key"] == "team", "the org plan did not sync on the summary call"

    invite = client.post(f"/api/v1/teams/{active['id']}/invite", headers=_headers(app, user),
                         json={"email": "second@example.test", "role": "collaborator"})
    assert invite.status_code == 201, invite.get_json()
    assert Organization.query.filter_by(owner_user_id=user.id).count() == 1


# ── 7. belonging to other organizations is untouched ─────────────────────────

def test_membership_in_another_organization_is_not_disturbed(client, app, db):
    """Being a MEMBER of several orgs stays valid; only OWNING several does not."""
    user, own_org, _record = _solo_with_history(app, db)
    _upgrade(app, db, user)

    host = _mk_user(db, "host@other.test", plan="team")
    other_org = _mk_org(db, host, name="Partner Co")
    db.session.add(OrganizationMember(
        organization_id=other_org.id, user_id=user.id,
        role="collaborator", status="active",
    ))
    db.session.commit()

    client.post("/api/v1/teams", headers=_headers(app, user), json={"name": "Acme Team"})

    # Still a member of both, still owner of exactly one.
    memberships = OrganizationMember.query.filter_by(user_id=user.id, status="active").all()
    assert {m.organization_id for m in memberships} == {own_org.id, other_org.id}
    assert Organization.query.filter_by(owner_user_id=user.id).count() == 1

    orgs = client.get("/api/v1/team/organizations", headers=_headers(app, user))
    assert {o["organization"]["id"] for o in orgs.get_json()["organizations"]} == {
        own_org.id, other_org.id
    }


def test_a_member_of_someone_elses_org_can_still_switch_to_it(client, app, db):
    user, own_org, _record = _solo_with_history(app, db)
    _upgrade(app, db, user)

    host = _mk_user(db, "host2@other.test", plan="team")
    other_org = _mk_org(db, host, name="Partner Two")
    db.session.add(OrganizationMember(
        organization_id=other_org.id, user_id=user.id,
        role="collaborator", status="active",
    ))
    db.session.commit()

    resp = client.post("/api/v1/team/organizations/active", headers=_headers(app, user),
                       json={"organization_id": other_org.id})
    assert resp.status_code == 200, resp.get_json()
    assert user.active_organization_id == other_org.id

    # And switching back returns the original org, memory intact.
    client.post("/api/v1/team/organizations/active", headers=_headers(app, user),
                json={"organization_id": own_org.id})
    assert UserSession.query.filter_by(session_id="cont-1").one().organization_id == own_org.id


# ── 8. solo behaviour is unchanged ───────────────────────────────────────────

def test_a_solo_user_who_never_upgrades_is_unaffected(client, app, db):
    user, org, record = _solo_with_history(app, db, email="stillsolo@example.test")

    assert Organization.query.filter_by(owner_user_id=user.id).count() == 1
    assert UserSession.query.filter_by(session_id="cont-1").one().organization_id == org.id
    assert DecisionRecord.query.get(record.id).organization_id == org.id


def test_a_sub_team_user_still_cannot_create_or_reuse_a_team_org(client, app, db):
    """The collaboration gate runs before any of this."""
    user, _org, _record = _solo_with_history(app, db, email="nogate@example.test")

    resp = client.post("/api/v1/teams", headers=_headers(app, user),
                       json={"name": "Sneaky Team"})
    assert resp.status_code == 403
    assert resp.get_json()["required_plan"] == "team"
    assert Organization.query.filter_by(owner_user_id=user.id).count() == 1


def test_a_user_with_no_prior_org_still_gets_one(client, app, db):
    """The create path must still work for a user who somehow has none."""
    user = _mk_user(db, "fresh@example.test", plan="team")
    Organization.query.filter_by(owner_user_id=user.id).delete()
    OrganizationMember.query.filter_by(user_id=user.id).delete()
    user.active_organization_id = None
    db.session.commit()

    resp = client.post("/api/v1/teams", headers=_headers(app, user),
                       json={"name": "Brand New"})
    assert resp.status_code in (200, 201), resp.get_json()
    assert Organization.query.filter_by(owner_user_id=user.id).count() == 1


# ── entitlement freshness: the gate must read the CURRENT plan ───────────────
#
# A subscription change writes user.subscription_plan and nothing else, so
# org.plan_key is stale until something syncs it. The by-id endpoints
# (_require_org_access, invitation accept) never went through org resolution,
# where that sync lived. On an upgrade that failed closed; on a DOWNGRADE it
# failed open.

def _invite(client, app, user, org_id, email):
    return client.post(f"/api/v1/teams/{org_id}/invite", headers=_headers(app, user),
                       json={"email": email, "role": "collaborator"})


def test_upgrade_is_honoured_immediately_on_a_direct_api_invite(client, app, db):
    """1. No org-aware request in between -- the invite itself must sync."""
    user, org, _record = _solo_with_history(app, db, email="fresh-up@example.test")
    assert org.plan_key == "free"

    _upgrade(app, db, user, plan="team")
    # Deliberately NO /team/summary call: straight to the protected endpoint
    # while org.plan_key is still 'free'.
    assert Organization.query.get(org.id).plan_key == "free"

    resp = _invite(client, app, user, org.id, "colleague@example.test")
    assert resp.status_code == 201, resp.get_json()
    assert Organization.query.get(org.id).plan_key == "team"


def test_downgrade_blocks_a_direct_api_invite_using_the_stale_plan(client, app, db):
    """2a. The fail-open case. Was: stale 'team' let the invite through."""
    user, org, _record = _solo_with_history(app, db, email="fresh-down@example.test")
    _upgrade(app, db, user, plan="team")
    assert _invite(client, app, user, org.id, "first@example.test").status_code == 201

    # Downgrade, then go straight at the API with org.plan_key still 'team'.
    _upgrade(app, db, user, plan="free")
    assert Organization.query.get(org.id).plan_key == "team"

    resp = _invite(client, app, user, org.id, "second@example.test")
    assert resp.status_code == 403, resp.get_json()
    assert resp.get_json()["reason"] == "plan_not_eligible"
    assert Organization.query.get(org.id).plan_key == "free"
    assert OrganizationInvitation.query.filter_by(email="second@example.test").count() == 0


def test_downgrade_blocks_acceptance_using_stale_team_entitlement(client, app, db):
    """2b. The invitee is not a member, so accept never resolved the org either."""
    user, org, _record = _solo_with_history(app, db, email="fresh-acc@example.test")
    _upgrade(app, db, user, plan="team")

    invitee = _mk_user(db, "joiner@example.test", plan="free")
    assert _invite(client, app, user, org.id, invitee.email).status_code == 201
    token = OrganizationInvitation.query.filter_by(email=invitee.email).one().token

    _upgrade(app, db, user, plan="free")
    assert Organization.query.get(org.id).plan_key == "team"

    resp = client.post(f"/api/v1/teams/invitations/{token}/accept",
                       headers=_headers(app, invitee))
    assert resp.status_code == 403, resp.get_json()
    assert resp.get_json()["reason"] == "plan_not_eligible"
    assert OrganizationMember.query.filter_by(
        organization_id=org.id, user_id=invitee.id
    ).count() == 0


def test_the_sync_follows_the_owner_not_the_caller(client, app, db):
    """3. A member's own subscription must not move someone else's org."""
    owner, org, _record = _solo_with_history(app, db, email="theowner@example.test")
    _upgrade(app, db, owner, plan="team")
    client.get("/api/v1/team/summary", headers=_headers(app, owner))
    assert Organization.query.get(org.id).plan_key == "team"

    member = _mk_user(db, "member-free@example.test", plan="free")
    db.session.add(OrganizationMember(
        organization_id=org.id, user_id=member.id, role="collaborator", status="active",
    ))
    member.active_organization_id = org.id
    db.session.commit()

    # The member is on 'free'. Their request must not downgrade the owner's org.
    resp = client.get(f"/api/v1/teams/{org.id}", headers=_headers(app, member))
    assert resp.status_code == 200, resp.get_json()
    assert Organization.query.get(org.id).plan_key == "team", (
        "a member's personal subscription changed the organization's plan"
    )


def test_the_sync_does_not_disturb_other_organizations(client, app, db):
    """4. Switching and cross-org membership are unaffected."""
    user, own_org, _record = _solo_with_history(app, db, email="multi@example.test")
    _upgrade(app, db, user, plan="team")

    host = _mk_user(db, "host3@other.test", plan="team")
    other_org = _mk_org(db, host, name="Partner Three")
    db.session.add(OrganizationMember(
        organization_id=other_org.id, user_id=user.id, role="collaborator", status="active",
    ))
    db.session.commit()

    client.get(f"/api/v1/teams/{own_org.id}", headers=_headers(app, user))

    # The other org still follows ITS owner, untouched.
    assert Organization.query.get(other_org.id).plan_key == "team"
    assert Organization.query.get(other_org.id).owner_user_id == host.id

    switched = client.post("/api/v1/team/organizations/active", headers=_headers(app, user),
                           json={"organization_id": other_org.id})
    assert switched.status_code == 200
    assert user.active_organization_id == other_org.id
