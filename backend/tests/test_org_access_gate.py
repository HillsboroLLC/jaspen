"""Organization membership gate (SSO Part 1: the authorization fix).

Being the creator of organization work no longer grants access once the
creator is removed from the organization or loses their seat. Personal work is
unchanged, active members are unchanged, and the rollout flag decides whether
the rule refuses (enforce), only records (report), or does nothing (off).

Share links: ownership comes from the underlying report; a removed creator
loses management of the organization's links, the organization's owners and
admins can list (metadata only) and turn them off, links whose owner could not
be determined are held for review, and personal links are unchanged.
"""
import os
import sqlite3
from datetime import datetime

import pytest
import sqlalchemy as sa
from flask_jwt_extended import create_access_token

from app import org_access, share_ownership
from app.models import (
    OrganizationMember,
    OrgAccessShadowEvent,
    SharedArtifact,
    SharedArtifactOwnership,
    UserSession,
)
from app.models_plan_jobs import PlanBuildJob
from app.models_studio import StudioWorkspace
from app.routes.sessions import load_user_sessions
from app.scenarios_store import load_scenarios_data, save_scenarios_data
from app.scorecards import list_scorecard_rows, upsert_scorecard
from app.session_access import can_read_session, can_write_session
from app.sharing import new_token

from tests.test_session_org_ownership import (
    _add_member,
    _headers,
    _mk_org,
    _mk_user,
    _seed_project,
)


@pytest.fixture(autouse=True)
def _clean_gate_state(db):
    org_access.reset_dedup()
    OrgAccessShadowEvent.query.delete()
    SharedArtifactOwnership.query.delete()
    SharedArtifact.query.delete()
    StudioWorkspace.query.delete()
    PlanBuildJob.query.delete()
    db.session.commit()
    yield
    org_access.reset_dedup()


@pytest.fixture
def enforce(monkeypatch):
    monkeypatch.setenv('ORG_ACCESS_ENFORCEMENT', 'enforce')


@pytest.fixture
def report(monkeypatch):
    monkeypatch.setenv('ORG_ACCESS_ENFORCEMENT', 'report')


@pytest.fixture
def team(db):
    owner = _mk_user(db, 'owner@acme.test')
    org = _mk_org(db, owner)
    member = _mk_user(db, 'member@acme.test')
    _add_member(db, org, member, role='creator')
    project = _seed_project(db, org, member, session_id='org-proj', visibility='team')
    return {'org': org, 'owner': owner, 'member': member, 'project': project}


def _remove(client, app, team):
    membership = OrganizationMember.query.filter_by(
        organization_id=team['org'].id, user_id=team['member'].id,
    ).one()
    response = client.delete(
        f'/api/v1/team/members/{membership.id}', headers=_headers(app, team['owner']),
    )
    assert response.status_code == 200, response.get_json()


def _events(user_id=None):
    query = OrgAccessShadowEvent.query
    if user_id:
        query = query.filter_by(user_id=str(user_id))
    return query.all()


def _personal_project(db, user, session_id='personal-proj'):
    row = UserSession(
        user_id=user.id, session_id=session_id, name='Mine', organization_id=None,
        created_by_user_id=user.id, visibility='private',
        payload={'session_id': session_id, 'name': 'Mine', 'chat_history': []},
    )
    db.session.add(row)
    db.session.commit()
    return row


# --- the mode flag -----------------------------------------------------------

def test_default_mode_is_report(monkeypatch):
    monkeypatch.delenv('ORG_ACCESS_ENFORCEMENT', raising=False)
    assert org_access.enforcement_mode() == 'report'


def test_unknown_mode_falls_back_to_report(monkeypatch):
    monkeypatch.setenv('ORG_ACCESS_ENFORCEMENT', 'enforcing')
    assert org_access.enforcement_mode() == 'report'


# --- active members and personal work are unchanged --------------------------

def test_active_member_keeps_access_to_their_org_work(client, app, team, enforce):
    response = client.get('/api/v1/sessions/org-proj', headers=_headers(app, team['member']))
    assert response.status_code == 200
    assert 'org-proj' in load_user_sessions(team['member'].id)
    assert can_write_session(team['project'], team['member']) is True
    assert _events() == []


def test_enforced_sso_org_requires_an_sso_session_for_that_org(client, app, db, team, enforce):
    team['org'].sso_enforced = True
    team['org'].sso_enforced_at = datetime.utcnow()
    team['org'].sso_grace_until = None
    db.session.commit()

    password_response = client.get(
        '/api/v1/sessions/org-proj', headers=_headers(app, team['member']),
    )
    assert password_response.status_code == 404
    assert any(event.reason == 'sso_required' for event in _events(team['member'].id))

    with app.app_context():
        sso_token = create_access_token(
            identity=str(team['member'].id),
            additional_claims={
                'auth_method': 'sso',
                'sso_org': str(team['org'].id),
                'auth_time': int(datetime.utcnow().timestamp()),
            },
        )
    sso_response = client.get(
        '/api/v1/sessions/org-proj',
        headers={'Authorization': f'Bearer {sso_token}'},
    )
    assert sso_response.status_code == 200


def test_personal_work_survives_removal(client, app, db, team, enforce):
    _personal_project(db, team['member'])
    memory = UserSession(user_id=team['member'].id, session_id='__user_memory__',
                         organization_id=team['org'].id, payload={})
    db.session.add(memory)
    db.session.commit()
    _remove(client, app, team)

    sessions = load_user_sessions(team['member'].id)
    assert 'personal-proj' in sessions
    assert '__user_memory__' in sessions
    response = client.get('/api/v1/sessions/personal-proj', headers=_headers(app, team['member']))
    assert response.status_code == 200


def test_remaining_members_keep_the_removed_members_work(client, app, team, enforce):
    _remove(client, app, team)
    response = client.get('/api/v1/sessions/org-proj', headers=_headers(app, team['owner']))
    assert response.status_code == 200


# --- removed and seat-revoked members are refused on every path --------------

def test_removed_member_cannot_read_their_former_org_work(client, app, team, enforce):
    _remove(client, app, team)
    headers = _headers(app, team['member'])

    response = client.get('/api/v1/sessions/org-proj', headers=headers)
    assert response.status_code == 404
    assert response.get_json()['code'] == 'not_found'

    listing = client.get('/api/v1/sessions', headers=headers).get_json()
    assert 'org-proj' not in {item['session_id'] for item in listing['items']}
    assert 'org-proj' not in load_user_sessions(team['member'].id)
    assert can_read_session(team['project'], team['member']) is False


def test_seat_revoked_member_is_refused_like_a_removed_one(app, db, team, enforce):
    membership = OrganizationMember.query.filter_by(
        organization_id=team['org'].id, user_id=team['member'].id,
    ).one()
    membership.status = 'suspended'
    db.session.commit()

    assert can_read_session(team['project'], team['member']) is False
    assert 'org-proj' not in load_user_sessions(team['member'].id)


def test_removed_member_save_is_refused_without_forking(client, app, team, enforce):
    _remove(client, app, team)
    response = client.post('/api/v1/sessions', headers=_headers(app, team['member']), json={
        'session_id': 'org-proj', 'name': 'Overwrite', 'chat_history': [],
    })
    assert response.status_code == 404
    rows = UserSession.query.filter_by(session_id='org-proj').all()
    assert len(rows) == 1
    assert rows[0].name == 'Shared project'


def test_removed_member_ai_thread_endpoints_answer_not_found(client, app, team, enforce):
    _remove(client, app, team)
    headers = _headers(app, team['member'])
    assert client.get('/api/v1/ai-agent/threads/org-proj', headers=headers).status_code == 404
    # This endpoint tolerates a missing row; an unreadable row must not be
    # softened into "missing".
    assert client.get('/api/v1/ai-agent/threads/org-proj/usage', headers=headers).status_code == 404
    listing = client.get('/api/v1/ai-agent/threads', headers=headers).get_json()
    assert 'org-proj' not in str(listing)


def test_scenario_data_is_hidden_and_never_cleared(db, client, app, team, enforce):
    team['project'].scenarios_json = {'scenarios': {'s1': {'label': 'Plan A'}}}
    db.session.commit()
    _remove(client, app, team)

    assert 'org-proj' not in load_scenarios_data(team['member'].id)
    # Saving the (filtered) data back must not wipe the organization's row.
    assert save_scenarios_data(team['member'].id, {}) is True
    db.session.refresh(team['project'])
    assert team['project'].scenarios_json == {'scenarios': {'s1': {'label': 'Plan A'}}}


def test_scenario_save_never_writes_onto_former_org_work(db, client, app, team, enforce):
    _remove(client, app, team)
    assert save_scenarios_data(team['member'].id, {'org-proj': {'scenarios': {'x': {}}}}) is True
    rows = UserSession.query.filter_by(session_id='org-proj').all()
    assert len(rows) == 1
    assert not rows[0].scenarios_json


def test_removed_member_scorecards_are_hidden(db, client, app, team, enforce):
    upsert_scorecard(
        user_id=team['member'].id, thread_id='org-proj',
        payload={'id': 'card-org', 'project_name': 'Org idea', 'jaspen_score': 70},
        organization_id=team['org'].id,
    )
    db.session.commit()
    assert [row.id for row in list_scorecard_rows(team['member'].id, thread_id='org-proj')] == ['card-org']
    _remove(client, app, team)
    assert list_scorecard_rows(team['member'].id, thread_id='org-proj') == []

    response = client.get(
        '/api/v1/strategy/threads/org-proj/scorecards/card-org/attributes',
        headers=_headers(app, team['member']),
    )
    assert response.status_code in (403, 404)


def test_removed_member_cannot_read_a_finished_plan_job(db, client, app, team, enforce):
    job = PlanBuildJob(
        user_id=team['member'].id, thread_id='org-proj', status='done',
        request_json={}, result_json={'project_wbs': {'tasks': ['secret']}}, result_status=200,
        heartbeat_at=datetime.utcnow(),
    )
    db.session.add(job)
    db.session.commit()
    url = f'/api/v1/strategy/threads/org-proj/ai-wbs/jobs/{job.id}'

    before = client.get(url, headers=_headers(app, team['member']))
    assert before.status_code == 200
    assert before.get_json()['result']['project_wbs']['tasks'] == ['secret']

    _remove(client, app, team)
    after = client.get(url, headers=_headers(app, team['member']))
    assert after.status_code == 404
    assert 'secret' not in str(after.get_json())


def test_removed_member_loses_studio_workspaces(db, client, app, team, enforce):
    workspace = StudioWorkspace(
        user_id=team['member'].id, organization_id=team['org'].id,
        created_by_user_id=team['member'].id, title='Org eval', rubric={},
    )
    db.session.add(workspace)
    db.session.commit()
    _remove(client, app, team)
    headers = _headers(app, team['member'])
    listing = client.get('/api/v1/studio/workspaces', headers=headers).get_json()
    assert listing['workspaces'] == []


# --- report and off modes ----------------------------------------------------

def test_report_mode_keeps_legacy_access_and_records_it(client, app, team, report):
    _remove(client, app, team)
    response = client.get('/api/v1/sessions/org-proj', headers=_headers(app, team['member']))
    assert response.status_code == 200

    events = _events(team['member'].id)
    assert events, 'report mode must record what enforcement would refuse'
    assert {event.mode for event in events} == {'report'}
    assert {event.reason for event in events} == {'not_active_member'}
    assert all(event.organization_id == team['org'].id for event in events)


def test_report_mode_records_each_access_once_per_window(client, app, team, report):
    _remove(client, app, team)
    headers = _headers(app, team['member'])
    client.get('/api/v1/sessions/org-proj', headers=headers)
    first = len(_events(team['member'].id))
    client.get('/api/v1/sessions/org-proj', headers=headers)
    assert len(_events(team['member'].id)) == first


def test_off_mode_is_the_emergency_rollback(client, app, team, monkeypatch):
    monkeypatch.setenv('ORG_ACCESS_ENFORCEMENT', 'off')
    _remove(client, app, team)
    response = client.get('/api/v1/sessions/org-proj', headers=_headers(app, team['member']))
    assert response.status_code == 200
    assert _events() == []


def test_recorded_events_hold_identifiers_only_and_expire(client, app, db, team, report):
    team['project'].name = 'Confidential acquisition of Globex'
    db.session.add(OrgAccessShadowEvent(
        created_at=datetime(2020, 1, 1), mode='report', path='old', resource_type='user_session',
        reason='not_active_member',
    ))
    db.session.commit()
    _remove(client, app, team)
    client.get('/api/v1/sessions/org-proj', headers=_headers(app, team['member']))

    events = _events()
    assert events and all(event.path != 'old' for event in events), 'rows past retention are pruned'
    stored = ' '.join(
        str(getattr(event, column.name)) for event in events for column in OrgAccessShadowEvent.__table__.columns
    )
    assert 'Confidential' not in stored and 'Globex' not in stored


def test_admin_can_review_recorded_events(client, app, team, report, admin_user, admin_auth_headers):
    _remove(client, app, team)
    client.get('/api/v1/sessions/org-proj', headers=_headers(app, team['member']))
    response = client.get('/api/v1/admin/org-access/events', headers=admin_auth_headers)
    assert response.status_code == 200
    body = response.get_json()
    assert body['mode'] == 'report'
    assert body['total'] >= 1
    assert body['recent'][0]['user_email'] == 'member@acme.test'

    denied = client.get('/api/v1/admin/org-access/events', headers=_headers(app, team['owner']))
    assert denied.status_code == 403


# --- share links -------------------------------------------------------------

SNAPSHOT_SECRET = 'Confidential pricing: $41k per seat'


def _link(db, owner, thread_id, *, state=None):
    link = SharedArtifact(
        token=new_token(), owner_user_id=owner.id, thread_id=thread_id,
        artifact_type='scorecard', title='Org idea scorecard',
        snapshot_json={'scorecard': {'project_name': 'Org idea', 'executive_summary': SNAPSHOT_SECRET}},
        include_evidence=False, disclosure_settings={}, created_at=datetime.utcnow(), view_count=0,
    )
    db.session.add(link)
    db.session.flush()
    if state is None:
        share_ownership.record_for_new_link(link)
    else:
        db.session.add(SharedArtifactOwnership(shared_artifact_id=link.id, state=state, source='test'))
    db.session.commit()
    return link


@pytest.fixture
def paid(db, team):
    for key in ('owner', 'member'):
        team[key].subscription_plan = 'starter'
        team[key].subscription_status = 'active'
    db.session.commit()
    return team


def test_ownership_comes_from_the_underlying_report(db, paid):
    link = _link(db, paid['member'], 'org-proj')
    row = db.session.get(SharedArtifactOwnership, link.id)
    assert (row.state, row.organization_id) == ('organization', paid['org'].id)

    _personal_project(db, paid['member'], session_id='mine')
    personal = _link(db, paid['member'], 'mine')
    assert db.session.get(SharedArtifactOwnership, personal.id).state == 'personal'


def test_creating_a_link_records_its_ownership(client, app, db, paid):
    from app.routes.sessions import save_user_sessions
    save_user_sessions(paid['member'].id, {'org-proj': {'session_id': 'org-proj', 'name': 'Shared project', 'chat_history': []}})
    upsert_scorecard(user_id=paid['member'].id, thread_id='org-proj',
                     payload={'id': 'card-1', 'project_name': 'Org idea', 'jaspen_score': 70},
                     organization_id=paid['org'].id)
    db.session.commit()
    response = client.post('/api/v1/shares', headers=_headers(app, paid['member']), json={
        'artifact_type': 'scorecard', 'thread_id': 'org-proj', 'scorecard_id': 'card-1',
        'disclosure_review_confirmed': True,
    })
    assert response.status_code == 201, response.get_json()
    row = db.session.get(SharedArtifactOwnership, response.get_json()['link']['id'])
    assert (row.state, row.organization_id) == ('organization', paid['org'].id)


def test_removed_creator_loses_management_but_the_link_keeps_its_audience(client, app, db, paid, enforce):
    link = _link(db, paid['member'], 'org-proj')
    _remove(client, app, paid)
    headers = _headers(app, paid['member'])

    assert client.get('/api/v1/shares', headers=headers).get_json()['links'] == []
    assert client.get(f'/api/v1/shares/manage/{link.token}', headers=headers).status_code == 404
    assert client.delete(f'/api/v1/shares/{link.id}', headers=headers).status_code == 404
    db.session.refresh(link)
    assert link.revoked_at is None

    # The public page is unchanged: same token, same audience, same content.
    public = client.get(f'/api/v1/shares/public/{link.token}')
    assert public.status_code == 200
    assert public.get_json()['snapshot']['scorecard']['project_name'] == 'Org idea'


def test_personal_links_are_unchanged_after_removal(client, app, db, paid, enforce):
    _personal_project(db, paid['member'], session_id='mine')
    link = _link(db, paid['member'], 'mine')
    _remove(client, app, paid)
    headers = _headers(app, paid['member'])
    assert [item['id'] for item in client.get('/api/v1/shares', headers=headers).get_json()['links']] == [link.id]
    assert client.get(f'/api/v1/shares/manage/{link.token}', headers=headers).status_code == 200
    assert client.get(f'/api/v1/shares/public/{link.token}').status_code == 200


def test_org_admin_view_is_metadata_only(client, app, db, paid, enforce):
    link = _link(db, paid['member'], 'org-proj')
    response = client.get(f"/api/v1/shares/org/{paid['org'].id}/links", headers=_headers(app, paid['owner']))
    assert response.status_code == 200
    [item] = response.get_json()['links']
    assert item['id'] == link.id
    assert item['owner_email'] == 'member@acme.test'
    assert item['owner_is_member'] is True
    for withheld in ('url', 'token', 'snapshot', 'snapshot_json', 'disclosure_settings', 'thread_id'):
        assert withheld not in item
    assert link.token not in str(response.get_json())
    assert SNAPSHOT_SECRET not in str(response.get_json())


def test_org_admin_sees_private_project_titles_only_if_they_can_read_them(client, app, db, paid, enforce):
    paid['project'].visibility = 'private'
    db.session.commit()
    _link(db, paid['member'], 'org-proj')
    [item] = client.get(
        f"/api/v1/shares/org/{paid['org'].id}/links", headers=_headers(app, paid['owner']),
    ).get_json()['links']
    assert item['title'] == 'Private project'
    assert item['title_hidden'] is True
    assert 'Org idea' not in str(item)


def test_org_admin_can_turn_off_a_removed_members_link(client, app, db, paid, enforce):
    link = _link(db, paid['member'], 'org-proj')
    _remove(client, app, paid)
    owner_headers = _headers(app, paid['owner'])

    [item] = client.get(f"/api/v1/shares/org/{paid['org'].id}/links", headers=owner_headers).get_json()['links']
    assert item['owner_is_member'] is False

    response = client.post(f"/api/v1/shares/org/{paid['org'].id}/links/{link.id}/revoke", headers=owner_headers)
    assert response.status_code == 200
    assert response.get_json()['link']['status'] == 'revoked'
    assert client.get(f'/api/v1/shares/public/{link.token}').status_code == 404


def test_org_link_endpoints_require_an_owner_or_admin(client, app, db, paid, enforce):
    link = _link(db, paid['member'], 'org-proj')
    org_id = paid['org'].id
    member_headers = _headers(app, paid['member'])
    assert client.get(f'/api/v1/shares/org/{org_id}/links', headers=member_headers).status_code == 403
    assert client.post(f'/api/v1/shares/org/{org_id}/links/{link.id}/revoke', headers=member_headers).status_code == 403

    outsider = _mk_user(db, 'outsider@other.test')
    _mk_org(db, outsider, name='Other')
    outsider_headers = _headers(app, outsider)
    assert client.get(f'/api/v1/shares/org/{org_id}/links', headers=outsider_headers).status_code == 404


def test_org_admin_cannot_touch_personal_or_other_org_links(client, app, db, paid, enforce):
    _personal_project(db, paid['member'], session_id='mine')
    personal = _link(db, paid['member'], 'mine')
    response = client.post(
        f"/api/v1/shares/org/{paid['org'].id}/links/{personal.id}/revoke", headers=_headers(app, paid['owner']),
    )
    assert response.status_code == 404
    db.session.refresh(personal)
    assert personal.revoked_at is None


def test_ambiguous_link_is_held_while_enforcing_and_resolvable(client, app, db, paid, enforce, admin_user, admin_auth_headers):
    link = _link(db, paid['member'], 'org-proj', state='ambiguous')
    assert client.get(f'/api/v1/shares/public/{link.token}').status_code == 404
    assert client.get(f'/api/v1/shares/manage/{link.token}', headers=_headers(app, paid['member'])).status_code == 404
    db.session.refresh(link)
    assert link.revoked_at is None, 'held for review, not revoked'

    listed = client.get('/api/v1/shares/admin/links?ownership=ambiguous', headers=admin_auth_headers).get_json()
    assert [item['id'] for item in listed['links']] == [link.id]

    resolved = client.post(f'/api/v1/shares/admin/links/{link.id}/ownership', headers=admin_auth_headers,
                           json={'state': 'organization', 'organization_id': paid['org'].id})
    assert resolved.status_code == 200
    assert client.get(f'/api/v1/shares/public/{link.token}').status_code == 200


def test_ambiguous_link_keeps_serving_in_report_mode_and_is_recorded(client, app, db, paid, report):
    link = _link(db, paid['member'], 'org-proj', state='ambiguous')
    assert client.get(f'/api/v1/shares/public/{link.token}').status_code == 200
    assert [event.reason for event in _events()] == ['ambiguous_ownership']


# --- migration ---------------------------------------------------------------

def _migration_module():
    from alembic.script import ScriptDirectory
    backend = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return ScriptDirectory(os.path.join(backend, 'migrations')).get_revision('d4e6f8a0b2c3').module


@pytest.mark.parametrize('org_ids, expected', [
    ([], ('ambiguous', None)),
    ([None], ('personal', None)),
    ([None, None], ('personal', None)),
    (['org-a'], ('organization', 'org-a')),
    (['org-a', 'org-a'], ('organization', 'org-a')),
    (['org-a', 'org-b'], ('ambiguous', None)),
    (['org-a', None], ('ambiguous', None)),
])
def test_migration_and_app_classify_identically(org_ids, expected):
    assert share_ownership.classify(org_ids) == expected
    assert _migration_module().classify(org_ids) == expected


def test_migration_backfills_existing_links_without_changing_them(tmp_path):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    db_path = tmp_path / 'pre.sqlite'
    raw = sqlite3.connect(db_path)
    raw.executescript('''
        CREATE TABLE shared_artifacts (id VARCHAR(36) PRIMARY KEY, owner_user_id VARCHAR(36),
            thread_id VARCHAR(255), title VARCHAR(255));
        CREATE TABLE user_sessions (id INTEGER PRIMARY KEY, user_id VARCHAR(36), session_id VARCHAR(255),
            organization_id VARCHAR(36), created_by_user_id VARCHAR(36));
        INSERT INTO user_sessions VALUES (1, 'u1', 't-org', 'org-1', 'u1');
        INSERT INTO user_sessions VALUES (2, 'u1', 't-personal', NULL, 'u1');
        INSERT INTO user_sessions VALUES (3, 'u1', 't-split', 'org-1', 'u1');
        INSERT INTO user_sessions VALUES (4, 'u1', 't-split', 'org-2', 'u1');
        INSERT INTO shared_artifacts VALUES ('l-org', 'u1', 't-org', 'A');
        INSERT INTO shared_artifacts VALUES ('l-personal', 'u1', 't-personal', 'B');
        INSERT INTO shared_artifacts VALUES ('l-split', 'u1', 't-split', 'C');
        INSERT INTO shared_artifacts VALUES ('l-missing', 'u1', 't-gone', 'D');
    ''')
    raw.commit()
    raw.close()

    engine = sa.create_engine(f'sqlite:///{db_path}')
    with engine.connect() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            _migration_module().upgrade()
        connection.commit()
        rows = dict(
            (link_id, (state, org_id)) for link_id, state, org_id in connection.execute(sa.text(
                'SELECT shared_artifact_id, state, organization_id FROM shared_artifact_ownership'
            ))
        )
        titles = [title for (title,) in connection.execute(sa.text('SELECT title FROM shared_artifacts ORDER BY id'))]
    engine.dispose()

    assert rows == {
        'l-org': ('organization', 'org-1'),
        'l-personal': ('personal', None),
        'l-split': ('ambiguous', None),
        'l-missing': ('ambiguous', None),
    }
    assert sorted(titles) == ['A', 'B', 'C', 'D']
