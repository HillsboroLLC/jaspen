"""Organization export: owner only, never widens access, no tokens or credentials, audited."""

from datetime import datetime

import pytest

from app.models import AdminAuditEvent, SharedArtifact, SharedArtifactOwnership, UserSession
from app.sharing import new_token

from tests.test_session_org_ownership import _add_member, _headers, _mk_org, _mk_user, _seed_project


@pytest.fixture(autouse=True)
def _clean_share_links(db):
    """The shared db fixture does not clear share links; never leak them."""
    yield
    SharedArtifactOwnership.query.delete()
    SharedArtifact.query.delete()
    db.session.commit()


def _setup(db):
    owner = _mk_user(db, 'owner@export.test')
    org = _mk_org(db, owner)
    member = _mk_user(db, 'member@export.test')
    _add_member(db, org, member, role='collaborator')
    _seed_project(db, org, owner, session_id='team-proj', visibility='team')
    _seed_project(db, org, member, session_id='member-private', visibility='private')
    outsider = _mk_user(db, 'outsider@export.test')
    other_org = _mk_org(db, outsider, name='Other')
    _seed_project(db, other_org, outsider, session_id='other-org-proj', visibility='team')
    link = SharedArtifact(token=new_token(), owner_user_id=owner.id, thread_id='team-proj', artifact_type='scorecard',
                          title='Team scorecard', snapshot_json={'x': 1}, include_evidence=False,
                          disclosure_settings={}, created_at=datetime.utcnow(), view_count=0)
    db.session.add(link)
    db.session.flush()
    db.session.add(SharedArtifactOwnership(shared_artifact_id=link.id, state='organization', organization_id=org.id))
    db.session.commit()
    return owner, member, org, link


def test_owner_exports_readable_work_without_tokens(client, app, db):
    owner, _member, org, link = _setup(db)
    response = client.get(f'/api/v1/teams/{org.id}/export', headers=_headers(app, owner))
    assert response.status_code == 200
    assert 'attachment' in response.headers['Content-Disposition']
    body = response.get_json()
    ids = {p['session_id'] for p in body['projects']}
    assert 'team-proj' in ids
    assert 'member-private' not in ids, "export must not widen access to private work"
    assert 'other-org-proj' not in ids
    assert body['share_links'][0]['id'] == link.id
    assert link.token not in response.get_data(as_text=True)
    assert body['data_sharing']['improve_jaspen'] is False
    assert AdminAuditEvent.query.filter_by(action='org_data_exported').count() == 1


def test_only_the_owner_can_export(client, app, db):
    _owner, member, org, _link = _setup(db)
    assert client.get(f'/api/v1/teams/{org.id}/export', headers=_headers(app, member)).status_code == 403
