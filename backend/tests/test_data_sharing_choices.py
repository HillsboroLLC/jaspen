"""Data-sharing choices default to off, change only by owner/admin, and are audited."""

from app.data_sharing import improve_jaspen_opted_in
from app.models import AdminAuditEvent, Organization

from tests.test_session_org_ownership import _add_member, _headers, _mk_org, _mk_user


def test_everything_is_off_by_default(client, app, db):
    owner = _mk_user(db, 'owner@privacy.test')
    org = _mk_org(db, owner)
    body = client.get(f'/api/v1/teams/{org.id}/data-sharing', headers=_headers(app, owner)).get_json()
    assert body['data_sharing']['improve_jaspen'] is False
    assert body['data_sharing']['decision_sharing_allowed'] is False
    assert improve_jaspen_opted_in(org) is False


def test_owner_opts_in_and_out_with_an_audit_trail(client, app, db):
    owner = _mk_user(db, 'owner2@privacy.test')
    org = _mk_org(db, owner)
    url = f'/api/v1/teams/{org.id}/data-sharing'
    on = client.put(url, json={'improve_jaspen': True}, headers=_headers(app, owner))
    assert on.status_code == 200 and on.get_json()['data_sharing']['improve_jaspen'] is True
    assert improve_jaspen_opted_in(db.session.get(Organization, org.id)) is True
    off = client.put(url, json={'improve_jaspen': False}, headers=_headers(app, owner))
    assert off.get_json()['data_sharing']['improve_jaspen'] is False
    events = AdminAuditEvent.query.filter_by(action='org_data_sharing_changed').all()
    assert len(events) == 2


def test_members_can_read_but_not_change(client, app, db):
    owner = _mk_user(db, 'owner3@privacy.test')
    org = _mk_org(db, owner)
    member = _mk_user(db, 'member3@privacy.test')
    _add_member(db, org, member, role='collaborator')
    url = f'/api/v1/teams/{org.id}/data-sharing'
    assert client.get(url, headers=_headers(app, member)).status_code == 200
    assert client.put(url, json={'improve_jaspen': True}, headers=_headers(app, member)).status_code == 403


def test_rejects_non_boolean_values(client, app, db):
    owner = _mk_user(db, 'owner4@privacy.test')
    org = _mk_org(db, owner)
    response = client.put(f'/api/v1/teams/{org.id}/data-sharing', json={'improve_jaspen': 'yes'}, headers=_headers(app, owner))
    assert response.status_code == 400
