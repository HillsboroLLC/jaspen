"""Collaboration is a Team-or-higher subscription entitlement.

The product rule these tests pin down:

    Collaboration is available only with an active Team-or-higher
    subscription. Free, Starter, Essential, the 300K promo, the founder
    offer, advisory packages, credit grants, or any other non-Team
    entitlement do not receive collaboration.

The 300K and founder cases matter most. Both confer real, active
entitlements -- a 300K holder is even lifted to Essential-equivalent access
by effective_plan_key() -- so a gate keyed on "has an entitlement" or "has
credits" instead of plan rank would wrongly let them through.
"""

import uuid
from datetime import datetime, timedelta

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from app.billing_config import effective_plan_key
from app.models import (
    AccountEntitlement,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    User,
)
from app.orgs import plan_allows_collaboration


def _make_user(db, email, plan="team", status="active"):
    user = User(
        email=email,
        name=email.split("@")[0],
        password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
        subscription_plan=plan,
        subscription_status=status,
        credits_remaining=1000,
        seat_limit=1,
        max_seats=1,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _make_org(db, owner, plan="team", max_total_paid_seats=None):
    org = Organization(
        id=str(uuid.uuid4()),
        name=f"{owner.name} Org",
        slug=f"org-{uuid.uuid4().hex[:8]}",
        owner_user_id=owner.id,
        plan_key=plan,
    )
    if max_total_paid_seats is not None:
        org.max_total_paid_seats = max_total_paid_seats
    db.session.add(org)
    db.session.flush()
    db.session.add(OrganizationMember(
        organization_id=org.id,
        user_id=owner.id,
        role="owner",
        status="active",
        joined_at=datetime.utcnow(),
    ))
    owner.active_organization_id = org.id
    db.session.commit()
    return org


def _headers(app, user):
    with app.app_context():
        return {"Authorization": f"Bearer {create_access_token(identity=str(user.id))}"}


def _invite(client, app, owner, org, email="invitee@example.com", role="collaborator"):
    return client.post(
        f"/api/v1/teams/{org.id}/invite",
        json={"email": email, "role": role},
        headers=_headers(app, owner),
    )


# --- entitlement, at the unit level ---------------------------------------

@pytest.mark.parametrize("plan,expected", [
    ("free", False),
    ("starter", False),
    ("essential", False),
    ("founder", False),          # alias -> essential
    ("growth", True),            # alias -> team
    ("team", True),
    ("business", True),
    ("enterprise", True),        # alias -> business
    ("enterprise_custom", True),
])
def test_plan_allows_collaboration(plan, expected):
    assert plan_allows_collaboration(plan) is expected


# --- Team and above may invite --------------------------------------------

@pytest.mark.parametrize("plan", ["team", "business", "enterprise_custom"])
def test_team_and_above_can_invite(client, app, db, plan):
    owner = _make_user(db, f"owner-{plan}@example.com", plan=plan)
    org = _make_org(db, owner, plan=plan)

    response = _invite(client, app, owner, org)

    assert response.status_code == 201, response.get_json()
    assert response.get_json()["invitation"]["email"] == "invitee@example.com"


# --- Below Team may not ----------------------------------------------------

@pytest.mark.parametrize("plan", ["free", "starter", "essential"])
def test_sub_team_plans_cannot_invite(client, app, db, plan):
    owner = _make_user(db, f"owner-{plan}@example.com", plan=plan)
    org = _make_org(db, owner, plan=plan)

    response = _invite(client, app, owner, org)

    assert response.status_code == 403
    body = response.get_json()
    assert body["reason"] == "plan_not_eligible"
    assert body["required_plan"] == "team"
    assert OrganizationInvitation.query.filter_by(organization_id=org.id).count() == 0


def test_300k_promo_holder_cannot_invite(client, app, db):
    """The 300K offer grants Essential-equivalent access, never collaboration."""
    owner = _make_user(db, "promo@example.com", plan="free")
    db.session.add(AccountEntitlement(
        user_id=owner.id,
        entitlement_key="300k_limited_time",
        source="stripe_300k_limited_time",
    ))
    db.session.commit()
    org = _make_org(db, owner, plan="free")

    # The entitlement is genuinely active and does lift entitlement checks --
    # that lift is exactly what must not reach collaboration.
    assert effective_plan_key(owner, app.config) == "essential"

    response = _invite(client, app, owner, org)

    assert response.status_code == 403
    assert response.get_json()["reason"] == "plan_not_eligible"


def test_founder_offer_cannot_invite(client, app, db):
    owner = _make_user(db, "founder@example.com", plan="founder")
    org = _make_org(db, owner, plan="founder")

    response = _invite(client, app, owner, org)

    assert response.status_code == 403
    assert response.get_json()["reason"] == "plan_not_eligible"


# --- Billing grace is separate from the entitlement -----------------------

def test_past_due_team_blocks_new_invites_but_keeps_members(client, app, db):
    owner = _make_user(db, "pastdue@example.com", plan="team", status="past_due")
    org = _make_org(db, owner, plan="team")
    member_user = _make_user(db, "existing@example.com", plan="free")
    db.session.add(OrganizationMember(
        organization_id=org.id,
        user_id=member_user.id,
        role="collaborator",
        status="active",
        joined_at=datetime.utcnow(),
    ))
    db.session.commit()

    response = _invite(client, app, owner, org)

    assert response.status_code == 403
    assert response.get_json()["reason"] == "subscription_not_current"

    # Dunning grace: the existing collaborator is untouched.
    existing = OrganizationMember.query.filter_by(
        organization_id=org.id, user_id=member_user.id
    ).one()
    assert existing.status == "active"


def test_active_team_subscription_can_invite(client, app, db):
    owner = _make_user(db, "current@example.com", plan="team", status="active")
    org = _make_org(db, owner, plan="team")

    assert _invite(client, app, owner, org).status_code == 201


# --- Pending invitations hold their seat ----------------------------------

def test_pending_invitation_reserves_a_seat(client, app, db):
    """Two paid seats: the owner holds one, one pending invite holds the other."""
    owner = _make_user(db, "seats@example.com", plan="team")
    org = _make_org(db, owner, plan="team", max_total_paid_seats=2)

    first = _invite(client, app, owner, org, email="first@example.com")
    assert first.status_code == 201

    second = _invite(client, app, owner, org, email="second@example.com")
    assert second.status_code == 409, second.get_json()
    assert "seat" in second.get_json()["error"].lower()


def test_expired_invitation_releases_its_seat(client, app, db):
    owner = _make_user(db, "expiry@example.com", plan="team")
    org = _make_org(db, owner, plan="team", max_total_paid_seats=2)

    assert _invite(client, app, owner, org, email="first@example.com").status_code == 201

    stale = OrganizationInvitation.query.filter_by(
        organization_id=org.id, email="first@example.com"
    ).one()
    stale.expires_at = datetime.utcnow() - timedelta(days=1)
    db.session.commit()

    assert _invite(client, app, owner, org, email="second@example.com").status_code == 201


# --- Accept re-checks the entitlement -------------------------------------

def test_accept_is_blocked_after_downgrade_below_team(client, app, db):
    owner = _make_user(db, "downgrade@example.com", plan="team")
    org = _make_org(db, owner, plan="team")
    invitee = _make_user(db, "joiner@example.com", plan="free")

    assert _invite(client, app, owner, org, email=invitee.email).status_code == 201
    token = OrganizationInvitation.query.filter_by(
        organization_id=org.id, email=invitee.email
    ).one().token

    # Owner downgrades to Essential before the invitee clicks the link.
    org.plan_key = "essential"
    owner.subscription_plan = "essential"
    db.session.commit()

    response = client.post(
        f"/api/v1/teams/invitations/{token}/accept",
        headers=_headers(app, invitee),
    )

    assert response.status_code == 403
    assert response.get_json()["reason"] == "plan_not_eligible"
    assert OrganizationMember.query.filter_by(
        organization_id=org.id, user_id=invitee.id
    ).count() == 0


def test_accept_succeeds_while_team_subscription_is_active(client, app, db):
    owner = _make_user(db, "stayteam@example.com", plan="team")
    org = _make_org(db, owner, plan="team")
    invitee = _make_user(db, "welcome@example.com", plan="free")

    assert _invite(client, app, owner, org, email=invitee.email).status_code == 201
    token = OrganizationInvitation.query.filter_by(
        organization_id=org.id, email=invitee.email
    ).one().token

    response = client.post(
        f"/api/v1/teams/invitations/{token}/accept",
        headers=_headers(app, invitee),
    )

    assert response.status_code == 200, response.get_json()
    member = OrganizationMember.query.filter_by(
        organization_id=org.id, user_id=invitee.id
    ).one()
    assert member.status == "active"
    assert member.role == "collaborator"


# --- Resending an invitation is gated too ---------------------------------

def test_resend_is_blocked_after_downgrade_below_team(client, app, db):
    """Resending is an invite action, so a downgraded org must not keep sending."""
    owner = _make_user(db, "resend-downgrade@example.com", plan="team")
    org = _make_org(db, owner, plan="team")

    assert _invite(client, app, owner, org).status_code == 201
    invite = OrganizationInvitation.query.filter_by(organization_id=org.id).one()
    original_expires = invite.expires_at

    # Owner downgrades below Team while the invitation is still pending.
    org.plan_key = "essential"
    owner.subscription_plan = "essential"
    db.session.commit()

    response = client.post(
        f"/api/v1/teams/{org.id}/invitations/{invite.id}/resend",
        headers=_headers(app, owner),
    )

    assert response.status_code == 403
    body = response.get_json()
    assert body["reason"] == "plan_not_eligible"
    assert body["required_plan"] == "team"

    # The gate runs before any mutation, so the invitation is untouched.
    refreshed = OrganizationInvitation.query.filter_by(id=invite.id).one()
    assert refreshed.status == "pending"
    assert refreshed.expires_at == original_expires


def test_past_due_team_cannot_resend_an_invitation(client, app, db):
    owner = _make_user(db, "resend-pastdue@example.com", plan="team")
    org = _make_org(db, owner, plan="team")

    assert _invite(client, app, owner, org).status_code == 201
    invite = OrganizationInvitation.query.filter_by(organization_id=org.id).one()

    owner.subscription_status = "past_due"
    db.session.commit()

    response = client.post(
        f"/api/v1/teams/{org.id}/invitations/{invite.id}/resend",
        headers=_headers(app, owner),
    )

    assert response.status_code == 403
    assert response.get_json()["reason"] == "subscription_not_current"


def test_active_team_can_still_resend_an_invitation(client, app, db):
    """The gate must not block orgs that are entitled and current."""
    owner = _make_user(db, "resend-ok@example.com", plan="team")
    org = _make_org(db, owner, plan="team")

    assert _invite(client, app, owner, org).status_code == 201
    invite = OrganizationInvitation.query.filter_by(organization_id=org.id).one()

    response = client.post(
        f"/api/v1/teams/{org.id}/invitations/{invite.id}/resend",
        headers=_headers(app, owner),
    )

    assert response.status_code == 200, response.get_json()


# --- Creating an org is itself gated --------------------------------------

@pytest.mark.parametrize("plan", ["free", "starter", "essential", "founder"])
def test_sub_team_plans_cannot_create_a_team_org(client, app, db, plan):
    """Otherwise a sub-Team user mints a Team-plan org and invites through it."""
    user = _make_user(db, f"creator-{plan}@example.com", plan=plan)

    response = client.post(
        "/api/v1/teams",
        json={"name": "Backdoor Co"},
        headers=_headers(app, user),
    )

    assert response.status_code == 403
    assert response.get_json()["reason"] == "plan_not_eligible"
    assert Organization.query.filter_by(owner_user_id=user.id).count() == 0


def test_team_plan_gets_its_existing_org_upgraded_not_replaced(client, app, db):
    """Was: asserted 201 and a freshly minted Organization.

    That encoded the behaviour we deliberately removed. Every user already owns
    a default organization from signup, and their projects, Decision Records
    and organizational memory hang off its id -- so this endpoint upgrades that
    organization in place rather than creating a second one and stranding
    everything in the first. See test_solo_to_team_continuity.py.
    """
    user = _make_user(db, "creator-team@example.com", plan="team")

    response = client.post(
        "/api/v1/teams",
        json={"name": "Real Team Co"},
        headers=_headers(app, user),
    )

    assert response.status_code == 200
    body = response.get_json()
    assert body["created"] is False
    assert body["reused_existing_organization"] is True

    # Exactly one owned organization, named as requested, on the Team plan.
    org = Organization.query.filter_by(owner_user_id=user.id).one()
    assert org.plan_key == "team"
    assert org.name == "Real Team Co"
    assert body["organization"]["id"] == org.id


def test_past_due_team_cannot_create_a_team_org(client, app, db):
    user = _make_user(db, "creator-pastdue@example.com", plan="team", status="past_due")

    response = client.post(
        "/api/v1/teams",
        json={"name": "Lapsed Co"},
        headers=_headers(app, user),
    )

    assert response.status_code == 403
    assert response.get_json()["reason"] == "subscription_not_current"
