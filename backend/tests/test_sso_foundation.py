"""Enterprise SSO foundation tests use a fake provider and never call WorkOS."""

from datetime import datetime
from urllib.parse import parse_qs, urlparse

import pytest

from app.models import Organization, OrganizationMember, SsoIdentity


@pytest.fixture(autouse=True)
def _restore_sso_config(app):
    """These tests switch SSO on; never let that leak into other tests."""
    keys = ('SSO_ENABLED', 'SSO_CLIENT_FACTORY')
    saved = {key: app.config.get(key) for key in keys}
    yield
    for key, value in saved.items():
        if value is None:
            app.config.pop(key, None)
        else:
            app.config[key] = value


class FakeSsoClient:
    def __init__(self, profile=None):
        self.profile = profile or {}

    def authorization_url(self, *, organization_id, state):
        return f"https://provider.test/authorize?organization={organization_id}&state={state}"

    def authenticate(self, *, code):
        assert code == 'test-code'
        return dict(self.profile)


def _enterprise_org(db, test_user):
    org = Organization(
        name='Acme',
        owner_user_id=test_user.id,
        plan_key='enterprise_custom',
        workos_organization_id='org_workos_test',
        sso_status='active',
        sso_mfa_attested_by=test_user.id,
        sso_mfa_attested_at=datetime.utcnow(),
    )
    db.session.add(org)
    db.session.flush()
    db.session.add(OrganizationMember(
        organization_id=org.id,
        user_id=test_user.id,
        role='owner',
        status='active',
        joined_at=datetime.utcnow(),
    ))
    db.session.commit()
    return org


def _start(client, org):
    response = client.post('/api/v1/auth/sso/start', json={
        'organization_id': org.id,
        'next': '/new',
    })
    assert response.status_code == 200, response.get_json()
    url = response.get_json()['authorization_url']
    return parse_qs(urlparse(url).query)['state'][0]


def test_sso_is_off_by_default(client):
    assert client.get('/api/v1/auth/sso/status').get_json() == {'enabled': False}
    response = client.post('/api/v1/auth/sso/start', json={'organization_id': 'anything'})
    assert response.status_code == 404
    assert response.get_json()['code'] == 'sso_not_available'


def test_sso_start_uses_active_enterprise_org_and_single_use_state(client, app, db, test_user):
    org = _enterprise_org(db, test_user)
    denied_profile = {
        'id': 'profile_outsider',
        'connection_id': 'conn_123',
        'organization_id': org.workos_organization_id,
        'email': 'outsider@example.com',
    }
    app.config.update(SSO_ENABLED=True, SSO_CLIENT_FACTORY=lambda: FakeSsoClient(denied_profile))

    state = _start(client, org)
    first = client.get(f'/api/v1/auth/sso/callback?code=test-code&state={state}')
    assert first.status_code == 302
    assert 'sso_access_denied' in first.headers['Location']

    replay = client.get(f'/api/v1/auth/sso/callback?code=test-code&state={state}')
    assert replay.status_code == 302
    assert 'sso_invalid_state' in replay.headers['Location']


def test_sso_callback_links_existing_member_and_issues_scoped_session(client, app, db, test_user):
    org = _enterprise_org(db, test_user)
    profile = {
        'id': 'profile_123',
        'connection_id': 'conn_123',
        'organization_id': org.workos_organization_id,
        'email': test_user.email,
        'name': test_user.name,
    }
    app.config.update(SSO_ENABLED=True, SSO_CLIENT_FACTORY=lambda: FakeSsoClient(profile))

    state = _start(client, org)
    response = client.get(f'/api/v1/auth/sso/callback?code=test-code&state={state}')

    assert response.status_code == 302
    assert response.headers['Location'].endswith('/auth/callback?next=%2Fnew')
    assert client.get_cookie(app.config['JWT_ACCESS_COOKIE_NAME']) is not None
    identity = SsoIdentity.query.filter_by(organization_id=org.id, user_id=test_user.id).one()
    assert identity.provider_identity_id == 'profile_123'
    assert identity.connection_id == 'conn_123'
