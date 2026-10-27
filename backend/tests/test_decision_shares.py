from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from app.models import AdminAuditEvent, DecisionShare, Organization, OrganizationMember, User, UserSession


def _headers(app, user):
    with app.app_context():
        token = create_access_token(identity=str(user.id))
    return {'Authorization': f'Bearer {token}'}


def _card(card_id='card-1', name='Option One'):
    return {
        'id': card_id,
        'analysis_id': card_id,
        'project_name': name,
        'jaspen_score': 72,
        'tier': 'Strong',
        'strategic_rationale': 'Useful rationale',
        'evidence': [{'passage': 'private passage', 'token': 'secret-token'}],
        'connector_credentials': {'password': 'secret'},
    }


def _session(db, user, *, thread_id='thread-1', organization=None, visibility='private', cards=None):
    cards = cards or [_card()]
    row = UserSession(
        user_id=user.id,
        created_by_user_id=user.id,
        organization_id=organization.id if organization else None,
        session_id=thread_id,
        name='Synthetic decision',
        visibility=visibility,
        payload={'result': {'scorecard_snapshots': cards}},
        scenarios_json={},
    )
    db.session.add(row)
    db.session.commit()
    return row


def _org(db, owner, *, allowed=True, name='Synthetic Org'):
    org = Organization(
        name=name,
        owner_user_id=owner.id,
        settings={'data_sharing': {'decision_sharing_allowed': allowed}},
    )
    db.session.add(org)
    db.session.flush()
    db.session.add(OrganizationMember(
        organization_id=org.id,
        user_id=owner.id,
        role='owner',
        status='active',
    ))
    owner.active_organization_id = org.id
    db.session.commit()
    return org


def _user(db, email):
    user = User(
        email=email,
        name=email.split('@')[0],
        password_hash=generate_password_hash('ValidPass1', method='pbkdf2:sha256'),
        subscription_plan='team',
        credits_remaining=100,
        seat_limit=1,
        max_seats=1,
    )
    db.session.add(user)
    db.session.commit()
    return user


def _preview(client, headers, thread_id='thread-1', scorecard_id='card-1'):
    return client.post('/api/v1/decision-shares/preview', headers=headers, json={
        'thread_id': thread_id,
        'scorecard_id': scorecard_id,
    })


def _create(client, headers, sha, thread_id='thread-1', scorecard_id='card-1', confirmed=True):
    return client.post('/api/v1/decision-shares', headers=headers, json={
        'thread_id': thread_id,
        'scorecard_id': scorecard_id,
        'snapshot_sha256': sha,
        'preview_confirmed': confirmed,
    })


def test_preview_stores_nothing_and_excludes_sensitive_fields(client, db, app, test_user):
    _session(db, test_user)
    response = _preview(client, _headers(app, test_user))
    assert response.status_code == 200
    assert DecisionShare.query.count() == 0
    serialized = str(response.get_json()['snapshot']).lower()
    assert 'private passage' not in serialized
    assert 'secret-token' not in serialized
    assert 'connector_credentials' not in serialized


def test_confirmation_and_exact_preview_hash_are_required(client, db, app, test_user):
    _session(db, test_user)
    headers = _headers(app, test_user)
    preview = _preview(client, headers).get_json()
    missing = _create(client, headers, preview['snapshot_sha256'], confirmed=False)
    assert missing.status_code == 400
    mismatch = _create(client, headers, '0' * 64)
    assert mismatch.status_code == 409
    assert DecisionShare.query.count() == 0


def test_non_reader_is_hidden_and_org_sharing_must_be_enabled(client, db, app, test_user):
    org = _org(db, test_user, allowed=False)
    _session(db, test_user, organization=org, visibility='private')
    outsider = _user(db, 'outsider@example.com')
    assert _preview(client, _headers(app, outsider)).status_code == 404
    refused = _preview(client, _headers(app, test_user))
    assert refused.status_code == 403
    assert 'Team settings' in refused.get_json()['error']


def test_personal_account_can_create_and_withdraw_clears_content(client, db, app, test_user):
    _session(db, test_user)
    headers = _headers(app, test_user)
    preview = _preview(client, headers).get_json()
    created = _create(client, headers, preview['snapshot_sha256'])
    assert created.status_code == 201
    share_id = created.get_json()['share']['id']
    assert DecisionShare.query.get(share_id).snapshot_json
    withdrawn = client.delete(f'/api/v1/decision-shares/{share_id}', headers=headers)
    assert withdrawn.status_code == 200
    db.session.expire_all()
    row = DecisionShare.query.get(share_id)
    assert row.snapshot_json is None
    assert row.withdrawn_at is not None


def test_solo_default_organization_does_not_need_an_admin_setting(client, db, app, test_user):
    org = _org(db, test_user, allowed=False)
    org.plan_key = 'starter'
    _session(db, test_user, organization=org)
    db.session.commit()
    headers = _headers(app, test_user)
    preview = _preview(client, headers)
    assert preview.status_code == 200
    created = _create(client, headers, preview.get_json()['snapshot_sha256'])
    assert created.status_code == 201
    assert created.get_json()['share']['organization_id'] is None


def test_member_listing_and_organization_isolation(client, db, app, test_user):
    org = _org(db, test_user)
    member = _user(db, 'member@example.com')
    member.active_organization_id = org.id
    db.session.add(OrganizationMember(organization_id=org.id, user_id=member.id, role='collaborator', status='active'))
    _session(db, test_user, organization=org, visibility='team')
    db.session.commit()
    owner_headers = _headers(app, test_user)
    member_headers = _headers(app, member)
    owner_preview = _preview(client, owner_headers).get_json()
    member_preview = _preview(client, member_headers).get_json()
    assert _create(client, owner_headers, owner_preview['snapshot_sha256']).status_code == 201
    assert _create(client, member_headers, member_preview['snapshot_sha256']).status_code == 201
    member_rows = client.get('/api/v1/decision-shares', headers=member_headers).get_json()['shares']
    owner_rows = client.get('/api/v1/decision-shares', headers=owner_headers).get_json()['shares']
    assert len(member_rows) == 1
    assert member_rows[0]['user_id'] == member.id
    assert len(owner_rows) == 2

    other_owner = _user(db, 'other-owner@example.com')
    other_org = _org(db, other_owner, name='Other Org')
    DecisionShare.query.first().organization_id = other_org.id
    db.session.commit()
    isolated = client.get('/api/v1/decision-shares', headers=owner_headers).get_json()['shares']
    assert all(row['organization_id'] == org.id for row in isolated)


def test_staff_view_requires_admin_is_audited_and_hides_withdrawn_content(
    client, db, app, test_user, admin_user, admin_auth_headers,
):
    _session(db, test_user)
    headers = _headers(app, test_user)
    preview = _preview(client, headers).get_json()
    created = _create(client, headers, preview['snapshot_sha256']).get_json()['share']

    denied = client.get(f"/api/v1/admin/decision-shares/{created['id']}", headers=headers)
    assert denied.status_code == 403
    viewed = client.get(f"/api/v1/admin/decision-shares/{created['id']}", headers=admin_auth_headers)
    assert viewed.status_code == 200
    assert viewed.get_json()['snapshot']
    assert AdminAuditEvent.query.filter_by(action='decision_share_staff_view').count() == 1

    client.delete(f"/api/v1/decision-shares/{created['id']}", headers=headers)
    viewed_after = client.get(f"/api/v1/admin/decision-shares/{created['id']}", headers=admin_auth_headers)
    assert viewed_after.get_json()['snapshot'] is None
    assert AdminAuditEvent.query.filter_by(action='decision_share_staff_view').count() == 2
