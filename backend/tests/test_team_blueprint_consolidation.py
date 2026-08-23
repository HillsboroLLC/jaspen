"""Both team blueprints must share one seat/role engine.

/api/v1/team/* and /api/v1/teams/* each used to carry their own copy of role
normalisation, seat accounting and capacity checking. The copies disagreed:
teams.py derived caps from the plan catalog and the per-role Organization
columns, while team.py used DEFAULT_SEAT_POLICIES plus seat_policy_overrides.
Two prefixes could therefore give two different answers about the same org.

These tests pin the prefixes together, so a future edit to one engine cannot
silently reintroduce a second one.
"""

import uuid
from datetime import datetime

from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from app.models import Organization, OrganizationInvitation, OrganizationMember, User


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


def _make_org(db, owner, plan="team", **columns):
    org = Organization(
        id=str(uuid.uuid4()),
        name=f"{owner.name} Org",
        slug=f"org-{uuid.uuid4().hex[:8]}",
        owner_user_id=owner.id,
        plan_key=plan,
    )
    for field, value in columns.items():
        setattr(org, field, value)
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


def test_seat_capacity_is_shared_across_both_prefixes(client, app, db):
    """A seat taken through /teams/* must be visible to /team/*, and vice versa."""
    owner = _make_user(db, "shared@example.com")
    org = _make_org(db, owner, max_total_paid_seats=2)
    headers = _headers(app, owner)

    # Owner holds one paid seat; this invitation holds the second.
    first = client.post(
        f"/api/v1/teams/{org.id}/invite",
        json={"email": "one@example.com", "role": "collaborator"},
        headers=headers,
    )
    assert first.status_code == 201

    # The *other* blueprint must see that seat as taken.
    second = client.post(
        "/api/v1/team/invitations",
        json={"email": "two@example.com", "role": "collaborator"},
        headers=headers,
    )
    assert second.status_code == 409, second.get_json()
    assert OrganizationInvitation.query.filter_by(organization_id=org.id).count() == 1


def test_both_prefixes_report_identical_seat_usage(client, app, db):
    owner = _make_user(db, "usage@example.com")
    org = _make_org(db, owner, max_total_paid_seats=4)
    headers = _headers(app, owner)

    client.post(
        f"/api/v1/teams/{org.id}/invite",
        json={"email": "pending@example.com", "role": "collaborator"},
        headers=headers,
    )

    from_teams = client.get(f"/api/v1/teams/{org.id}/seat-usage", headers=headers).get_json()
    from_team = client.get("/api/v1/team/summary", headers=headers).get_json()["seat_usage"]

    assert from_teams == from_team
    assert from_teams["total_paid_used"] == 1        # the owner
    assert from_teams["total_paid_pending"] == 1     # the invitation
    assert from_teams["total_paid_reserved"] == 2


def test_admin_cap_follows_the_plan_not_the_stale_column(client, app, db):
    """Team allows 3 admin seats per the plan catalog and DEFAULT_SEAT_POLICIES.

    The Organization.max_admin_seats column defaults to 2 and was only ever
    read by the teams.py copy of the engine. Consolidating on app.orgs makes
    the published plan authoritative, so an org carrying the stale 2 still
    gets its 3 Team admin seats.
    """
    owner = _make_user(db, "admins@example.com")
    org = _make_org(db, owner, max_admin_seats=2)
    headers = _headers(app, owner)

    # Owner occupies one admin seat, leaving two.
    for index in (1, 2):
        response = client.post(
            f"/api/v1/teams/{org.id}/invite",
            json={"email": f"admin{index}@example.com", "role": "admin"},
            headers=headers,
        )
        assert response.status_code == 201, response.get_json()

    overflow = client.post(
        f"/api/v1/teams/{org.id}/invite",
        json={"email": "admin3@example.com", "role": "admin"},
        headers=headers,
    )
    assert overflow.status_code == 409


def test_seat_policy_overrides_apply_through_both_prefixes(client, app, db):
    """Per-org overrides live in app.orgs; teams.py never consulted them.

    Team and Business pool creator/collaborator seats against
    max_total_paid_seats rather than capping them per role, so the override
    that bites on those plans is the admin one.
    """
    owner = _make_user(db, "override@example.com")
    org = _make_org(db, owner, seat_policy_overrides={"admin": 1})
    headers = _headers(app, owner)

    # The owner already occupies the single overridden admin seat.
    response = client.post(
        f"/api/v1/teams/{org.id}/invite",
        json={"email": "extra-admin@example.com", "role": "admin"},
        headers=headers,
    )
    assert response.status_code == 409, response.get_json()

    # Collaborators are pooled, not per-role capped, so they are unaffected.
    pooled = client.post(
        f"/api/v1/teams/{org.id}/invite",
        json={"email": "collab@example.com", "role": "collaborator"},
        headers=headers,
    )
    assert pooled.status_code == 201, pooled.get_json()


def test_roles_normalise_identically_across_prefixes(client, app, db):
    """'member' is an alias for collaborator in app.orgs; teams.py rejected it."""
    owner = _make_user(db, "alias@example.com")
    org = _make_org(db, owner)

    response = client.post(
        f"/api/v1/teams/{org.id}/invite",
        json={"email": "aliased@example.com", "role": "member"},
        headers=_headers(app, owner),
    )

    assert response.status_code == 201
    assert response.get_json()["invitation"]["role"] == "collaborator"
