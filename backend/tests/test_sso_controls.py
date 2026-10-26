"""SSO enforcement, recovery, revoke and admin controls. Synthetic only: no
provider calls, no paid service, SSO off unless a test turns it on."""

import time
from datetime import datetime, timedelta

import pytest
from flask_jwt_extended import create_access_token

from app.models import AdminAuditEvent, OrgAccessShadowEvent, Organization, OrganizationMember, UserSession
from app.org_access import reset_dedup, sso_allows

from tests.test_session_org_ownership import _mk_user


@pytest.fixture(autouse=True)
def _isolated(app, db):
    saved = app.config.get('SSO_ENABLED')
    reset_dedup()
    OrgAccessShadowEvent.query.delete()
    db.session.commit()
    yield
    app.config['SSO_ENABLED'] = saved


def _token(app, user, *, sso_org=None, issued=None):
    claims = {}
    if sso_org:
        claims = {'auth_method': 'sso', 'sso_org': sso_org, 'auth_time': int(issued or time.time())}
    elif issued:
        claims = {'auth_time': int(issued)}
    with app.app_context():
        return {'Authorization': f"Bearer {create_access_token(identity=str(user.id), additional_claims=claims)}"}


@pytest.fixture
def org_setup(db):
    owner = _mk_user(db, 'owner@enterprise.test', plan='enterprise')
    owner.mfa_enabled = True
    member = _mk_user(db, 'member@enterprise.test', plan='enterprise')
    org = Organization(name='Enterprise', owner_user_id=owner.id, plan_key='enterprise_custom',
                       workos_organization_id='org_synthetic', sso_status='active')
    db.session.add(org)
    db.session.flush()
    for user, role in ((owner, 'owner'), (member, 'collaborator')):
        db.session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role=role, status='active'))
        user.active_organization_id = org.id
    db.session.add(UserSession(user_id=owner.id, session_id='ent-proj', name='Enterprise project',
                               organization_id=org.id, created_by_user_id=owner.id, visibility='team',
                               payload={'session_id': 'ent-proj', 'name': 'Enterprise project', 'chat_history': []}))
    db.session.commit()
    return {'org': org, 'owner': owner, 'member': member}


def _enforce(db, org, **fields):
    org.sso_enforced = True
    for key, value in fields.items():
        setattr(org, key, value)
    db.session.commit()


def test_orgs_without_enforcement_are_unchanged(client, app, org_setup):
    response = client.get('/api/v1/sessions/ent-proj', headers=_token(app, org_setup['member']))
    assert response.status_code == 200


def test_enforced_org_refuses_non_sso_sessions_and_accepts_its_sso(client, app, db, org_setup):
    _enforce(db, org_setup['org'])
    member = org_setup['member']
    assert client.get('/api/v1/sessions/ent-proj', headers=_token(app, member)).status_code == 404
    sso = _token(app, member, sso_org=org_setup['org'].id)
    assert client.get('/api/v1/sessions/ent-proj', headers=sso).status_code == 200
    other_org = _token(app, member, sso_org='some-other-org')
    assert client.get('/api/v1/sessions/ent-proj', headers=other_org).status_code == 404


def test_grace_window_admits_existing_sessions_until_it_ends(client, app, db, org_setup):
    _enforce(db, org_setup['org'], sso_grace_until=datetime.utcnow() + timedelta(hours=2))
    assert client.get('/api/v1/sessions/ent-proj', headers=_token(app, org_setup['member'])).status_code == 200
    org_setup['org'].sso_grace_until = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()
    assert client.get('/api/v1/sessions/ent-proj', headers=_token(app, org_setup['member'])).status_code == 404


def test_background_work_is_not_blocked_by_enforcement(app, db, org_setup):
    _enforce(db, org_setup['org'])
    with app.app_context():
        assert sso_allows(org_setup['org'].id) is True


def test_sign_everyone_out_refuses_older_sessions(client, app, db, org_setup):
    org = org_setup['org']
    before = time.time() - 60
    _enforce(db, org, sso_sessions_revoked_at=datetime.utcnow())
    stale = _token(app, org_setup['member'], sso_org=org.id, issued=before)
    assert client.get('/api/v1/sessions/ent-proj', headers=stale).status_code == 404
    fresh = _token(app, org_setup['member'], sso_org=org.id, issued=time.time() + 1)
    assert client.get('/api/v1/sessions/ent-proj', headers=fresh).status_code == 200


def test_recovery_admin_reaches_sso_settings_but_not_project_data(client, app, db, org_setup):
    org, owner = org_setup['org'], org_setup['owner']
    _enforce(db, org, sso_recovery_admin_user_id=owner.id)
    headers = _token(app, owner)
    settings = client.get(f'/api/v1/teams/{org.id}/sso', headers=headers)
    assert settings.status_code == 200
    assert settings.get_json()['sso']['enforced'] is True
    assert client.get('/api/v1/sessions/ent-proj', headers=headers).status_code == 404
    assert OrgAccessShadowEvent.query.filter_by(reason='sso_recovery_access', user_id=owner.id).count() == 1

    turned_off = client.patch(f'/api/v1/teams/{org.id}/sso', json={'enforced': False}, headers=headers)
    assert turned_off.status_code == 200
    assert client.get('/api/v1/sessions/ent-proj', headers=headers).status_code == 200
    assert AdminAuditEvent.query.filter_by(action='org_sso_settings_changed').count() == 1


def test_non_recovery_admin_without_sso_is_refused(client, app, db, org_setup):
    org = org_setup['org']
    other_admin = _mk_user(db, 'admin2@enterprise.test', plan='enterprise')
    db.session.add(OrganizationMember(organization_id=org.id, user_id=other_admin.id, role='admin', status='active'))
    _enforce(db, org, sso_recovery_admin_user_id=org_setup['owner'].id)
    response = client.get(f'/api/v1/teams/{org.id}/sso', headers=_token(app, other_admin))
    assert response.status_code == 403
    assert response.get_json()['code'] == 'sso_required'


def test_enforcing_requires_active_sso_and_an_mfa_recovery_admin(client, app, db, org_setup):
    org, owner, member = org_setup['org'], org_setup['owner'], org_setup['member']
    headers = _token(app, owner)
    app.config['SSO_ENABLED'] = False
    assert client.patch(f'/api/v1/teams/{org.id}/sso', json={'enforced': True}, headers=headers).get_json()['code'] == 'sso_not_active'
    app.config['SSO_ENABLED'] = True
    assert client.patch(f'/api/v1/teams/{org.id}/sso', json={'enforced': True}, headers=headers).get_json()['code'] == 'recovery_admin_required'
    not_admin = client.patch(f'/api/v1/teams/{org.id}/sso', json={'recovery_admin_user_id': member.id}, headers=headers)
    assert not_admin.status_code == 400
    owner.mfa_enabled = False
    db.session.commit()
    no_mfa = client.patch(f'/api/v1/teams/{org.id}/sso', json={'recovery_admin_user_id': owner.id}, headers=headers)
    assert no_mfa.get_json()['code'] == 'recovery_admin_mfa_required'
    owner.mfa_enabled = True
    db.session.commit()
    assert client.patch(f'/api/v1/teams/{org.id}/sso', json={'recovery_admin_user_id': owner.id}, headers=headers).status_code == 200
    enforced = client.patch(f'/api/v1/teams/{org.id}/sso', json={'enforced': True, 'grace_hours': 4}, headers=headers)
    assert enforced.status_code == 200
    body = enforced.get_json()['sso']
    assert body['enforced'] is True and body['grace_until']


def test_members_cannot_manage_sso(client, app, org_setup):
    response = client.get(f"/api/v1/teams/{org_setup['org'].id}/sso", headers=_token(app, org_setup['member']))
    assert response.status_code == 403


def test_staff_activation_requires_admin_flag_and_enterprise_plan(client, app, db, org_setup, admin_user, admin_auth_headers):
    org = org_setup['org']
    org.sso_status = 'off'
    db.session.commit()
    url = f'/api/v1/admin/organizations/{org.id}/sso'
    assert client.post(url, json={'status': 'active'}, headers=_token(app, org_setup['owner'])).status_code == 403
    app.config['SSO_ENABLED'] = False
    assert client.post(url, json={'status': 'active', 'workos_organization_id': 'org_x'}, headers=admin_auth_headers).get_json()['code'] == 'sso_not_enabled'
    app.config['SSO_ENABLED'] = True
    org.plan_key = 'team'
    db.session.commit()
    assert client.post(url, json={'status': 'active', 'workos_organization_id': 'org_x'}, headers=admin_auth_headers).get_json()['code'] == 'sso_plan_required'
    org.plan_key = 'enterprise_custom'
    db.session.commit()
    activated = client.post(url, json={'status': 'active', 'workos_organization_id': 'org_x'}, headers=admin_auth_headers)
    assert activated.status_code == 200
    assert activated.get_json() == {'organization_id': org.id, 'sso_status': 'active', 'sso_enforced': False}
