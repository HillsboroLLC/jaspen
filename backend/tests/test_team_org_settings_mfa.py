"""MFA policy on organization settings.

PATCH /api/v1/teams/<org_id>/settings raised NameError instead of applying a
policy: teams.py referenced MFA_POLICY_REQUIRED without importing it. Team
orgs short-circuited past both references and worked, which is why it went
unnoticed -- Business orgs and any sub-Team org asking for enforcement got a
500. EnterpriseAdmin calls this endpoint.
"""

import uuid
from datetime import datetime

import pytest
from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from app.models import Organization, OrganizationMember, User


def _owner_with_org(db, email, plan):
    user = User(
        email=email,
        name=email.split("@")[0],
        password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
        subscription_plan=plan,
        subscription_status="active",
        credits_remaining=10,
        seat_limit=1,
        max_seats=1,
    )
    db.session.add(user)
    db.session.commit()

    org = Organization(
        id=str(uuid.uuid4()),
        name=f"{user.name} Co",
        slug=f"org-{uuid.uuid4().hex[:8]}",
        owner_user_id=user.id,
        plan_key=plan,
    )
    db.session.add(org)
    db.session.flush()
    db.session.add(OrganizationMember(
        organization_id=org.id,
        user_id=user.id,
        role="owner",
        status="active",
        joined_at=datetime.utcnow(),
    ))
    db.session.commit()
    return user, org


def _patch_settings(client, app, user, org, settings):
    with app.app_context():
        headers = {"Authorization": f"Bearer {create_access_token(identity=str(user.id))}"}
    return client.patch(
        f"/api/v1/teams/{org.id}/settings",
        json={"settings": settings},
        headers=headers,
    )


def test_business_org_settings_do_not_500(client, app, db):
    user, org = _owner_with_org(db, "biz@example.com", "business")

    response = _patch_settings(client, app, user, org, {"mfa_policy": "optional"})

    assert response.status_code == 200, response.get_json()
    # Business enforces MFA regardless of what was asked for.
    assert response.get_json()["settings"]["mfa_policy"] == "required"


def test_team_org_can_set_an_optional_policy(client, app, db):
    user, org = _owner_with_org(db, "team@example.com", "team")

    response = _patch_settings(client, app, user, org, {"mfa_policy": "optional"})

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["settings"]["mfa_policy"] == "optional"


def test_team_org_can_require_mfa(client, app, db):
    user, org = _owner_with_org(db, "teamreq@example.com", "team")

    response = _patch_settings(client, app, user, org, {"mfa_policy": "required"})

    assert response.status_code == 200, response.get_json()
    assert response.get_json()["settings"]["mfa_policy"] == "required"


@pytest.mark.parametrize("plan", ["free", "starter", "essential"])
def test_sub_team_orgs_cannot_require_mfa(client, app, db, plan):
    user, org = _owner_with_org(db, f"sub-{plan}@example.com", plan)

    response = _patch_settings(client, app, user, org, {"mfa_policy": "required"})

    assert response.status_code == 400
    assert "Team or Business" in response.get_json()["error"]


def test_invalid_policy_is_rejected(client, app, db):
    user, org = _owner_with_org(db, "bogus@example.com", "team")

    response = _patch_settings(client, app, user, org, {"mfa_policy": "sometimes"})

    assert response.status_code == 400
    assert "mfa_policy" in response.get_json()["error"]
