"""Public share links: privacy of the frozen copy, limits, and controls."""

from datetime import datetime, timedelta

import pytest

from app.models import SharedArtifact, SharedArtifactReport
from app.routes.sessions import save_user_sessions
from app.scorecards import upsert_scorecard
from app.sharing import count_evidence_passages, sanitize_scorecard


THREAD = 'share-thread'
QUOTE = 'We closed three pilots last quarter at $4k each'


def _card(card_id, name, score=72, **extra):
    return {
        'id': card_id,
        'analysis_id': card_id,
        'project_name': name,
        'jaspen_score': score,
        'thread_id': THREAD,
        'user_id': 'secret-user',
        'evaluation_id': 'secret-eval',
        'meta': {'model_type': 'orbit', 'tool': 'score_batch'},
        '_baseline_scorecard': {'project_name': 'hidden baseline'},
        'scorecard_snapshots': [{'project_name': 'nested card'}],
        'executive_summary': f'{name} summary',
        'dimensions': {
            'fit': {
                'score': 80, 'label': 'Founder fit', 'rationale': 'Strong fit',
                'evidence': [QUOTE],
                'evidence_references': [{'excerpt': QUOTE, 'locator': 'msg-3', 'evidence_role': 'support'}],
            },
        },
        **extra,
    }


def _session():
    return {
        'session_id': THREAD,
        'name': 'Channel decision',
        'status': 'in_progress',
        'chat_history': [{'role': 'user', 'content': 'private chat text'}],
        'result': {},
        'scorecard_queue': [],
        'strategy_objective': 'balanced',
        'portfolio_summary': {'structure': '2 Leading Candidate', 'recommended_sequence': 'Commit to A.'},
    }


@pytest.fixture
def paid_user(db, test_user):
    test_user.subscription_plan = 'starter'
    test_user.subscription_status = 'active'
    db.session.commit()
    save_user_sessions(test_user.id, {THREAD: _session()})
    upsert_scorecard(user_id=test_user.id, thread_id=THREAD, payload=_card('card-a', 'Paid search'))
    upsert_scorecard(user_id=test_user.id, thread_id=THREAD, payload=_card('card-b', 'Podcasts', score=64))
    db.session.commit()
    return test_user


def _create(client, headers, **body):
    payload = {'artifact_type': 'scorecard', 'thread_id': THREAD, 'scorecard_id': 'card-a'}
    payload.update(body)
    return client.post('/api/v1/shares', json=payload, headers=headers)


def _token(response):
    return response.get_json()['link']['url'].rsplit('/', 1)[-1]


def test_sanitizer_keeps_scorecard_content_and_drops_private_fields():
    shared = sanitize_scorecard(_card('card-a', 'Paid search'), include_evidence=False, public_id='c1')

    assert shared['project_name'] == 'Paid search'
    assert shared['dimensions']['fit']['rationale'] == 'Strong fit'
    assert shared['id'] == 'c1' and shared['analysis_id'] == 'c1'
    for private in ('thread_id', 'user_id', 'evaluation_id', 'meta', '_baseline_scorecard', 'scorecard_snapshots'):
        assert private not in shared
    assert 'evidence' not in shared['dimensions']['fit']
    assert 'evidence_references' not in shared['dimensions']['fit']
    assert QUOTE not in str(shared)


def test_evidence_is_included_only_when_chosen_and_counted_once():
    card = _card('card-a', 'Paid search')
    shared = sanitize_scorecard(card, include_evidence=True, public_id='c1')

    assert shared['dimensions']['fit']['evidence'] == [QUOTE]
    assert count_evidence_passages(card) == 1   # same quote in two places


def test_free_plan_cannot_share(client, db, test_user, auth_headers):
    save_user_sessions(test_user.id, {THREAD: _session()})
    response = _create(client, auth_headers)
    assert response.status_code == 403
    assert response.get_json()['code'] == 'paid_plan_required'


def test_preview_reports_what_will_be_shared_without_creating_a_link(client, paid_user, auth_headers):
    response = client.post('/api/v1/shares/preview', json={
        'artifact_type': 'scorecard', 'thread_id': THREAD, 'scorecard_id': 'card-a',
    }, headers=auth_headers)

    assert response.status_code == 200
    data = response.get_json()
    assert data['summary']['evidence_quotes_available'] == 1
    assert data['summary']['evidence_quotes_included'] is False
    assert QUOTE not in str(data['snapshot'])
    assert SharedArtifact.query.count() == 0


def test_created_link_serves_a_frozen_noindexed_copy(client, db, paid_user, auth_headers):
    created = _create(client, auth_headers)
    assert created.status_code == 201
    link = created.get_json()['link']
    assert link['status'] == 'active'
    assert len(_token(created)) >= 40
    expires = datetime.fromisoformat(link['expires_at'].rstrip('Z'))
    assert timedelta(days=29) < expires - datetime.utcnow() <= timedelta(days=30)

    # Later edits to the live scorecard must not change the shared copy.
    upsert_scorecard(user_id=paid_user.id, thread_id=THREAD, payload=_card('card-a', 'Renamed later'))
    db.session.commit()

    public = client.get(f'/api/v1/shares/public/{_token(created)}')
    assert public.status_code == 200
    assert public.headers['X-Robots-Tag'].startswith('noindex')
    body = public.get_json()
    assert body['snapshot']['scorecard']['project_name'] == 'Paid search'
    assert 'private chat text' not in str(body)
    assert SharedArtifact.query.one().view_count == 1


def test_tradeoff_share_includes_every_included_card(client, paid_user, auth_headers):
    created = client.post('/api/v1/shares', json={
        'artifact_type': 'tradeoff', 'thread_id': THREAD, 'expires_in_days': 'never',
    }, headers=auth_headers)
    assert created.status_code == 201
    assert created.get_json()['link']['expires_at'] is None

    body = client.get(f'/api/v1/shares/public/{_token(created)}').get_json()
    names = [card['project_name'] for card in body['snapshot']['scorecards']]
    assert names == ['Paid search', 'Podcasts']
    assert body['snapshot']['portfolio_summary']['recommended_sequence'] == 'Commit to A.'


@pytest.mark.parametrize('value', [1, 45, 'forever'])
def test_only_allowed_expiry_choices_are_accepted(client, paid_user, auth_headers, value):
    assert _create(client, auth_headers, expires_in_days=value).status_code == 400


def test_revoked_and_expired_links_stop_serving(client, db, paid_user, auth_headers):
    first = _create(client, auth_headers)
    link_id = first.get_json()['link']['id']
    assert client.delete(f'/api/v1/shares/{link_id}', headers=auth_headers).status_code == 200
    assert client.get(f'/api/v1/shares/public/{_token(first)}').status_code == 404

    second = _create(client, auth_headers, expires_in_days=7)
    link = SharedArtifact.query.filter_by(id=second.get_json()['link']['id']).one()
    link.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.session.commit()
    assert client.get(f'/api/v1/shares/public/{_token(second)}').status_code == 404


def test_links_pause_when_owner_leaves_paid_plan(client, db, paid_user, auth_headers):
    created = _create(client, auth_headers)
    paid_user.subscription_plan = 'free'
    db.session.commit()
    assert client.get(f'/api/v1/shares/public/{_token(created)}').status_code == 404


def test_other_users_cannot_revoke_or_see_a_link(client, app, db, paid_user, auth_headers, admin_user):
    from flask_jwt_extended import create_access_token
    created = _create(client, auth_headers)
    link_id = created.get_json()['link']['id']
    with app.app_context():
        other = {'Authorization': f'Bearer {create_access_token(identity=str(admin_user.id))}'}
    assert client.delete(f'/api/v1/shares/{link_id}', headers=other).status_code == 404
    assert client.get('/api/v1/shares', headers=other).get_json()['links'] == []


def test_daily_and_active_limits_are_enforced(client, app, paid_user, auth_headers):
    app.config['SHARE_LINK_DAILY_CREATE_LIMIT'] = 2
    try:
        assert _create(client, auth_headers).status_code == 201
        assert _create(client, auth_headers).status_code == 201
        limited = _create(client, auth_headers)
        assert limited.status_code == 429
        assert limited.get_json()['code'] == 'daily_share_limit'
    finally:
        app.config.pop('SHARE_LINK_DAILY_CREATE_LIMIT', None)

    app.config['SHARE_LINK_ACTIVE_LIMIT'] = 2
    try:
        limited = _create(client, auth_headers)
        assert limited.get_json()['code'] == 'active_share_limit'
    finally:
        app.config.pop('SHARE_LINK_ACTIVE_LIMIT', None)


def test_admin_can_revoke_links_and_disable_sharing(client, paid_user, auth_headers, admin_auth_headers):
    created = _create(client, auth_headers)
    link_id = created.get_json()['link']['id']

    assert client.post(f'/api/v1/shares/admin/links/{link_id}/revoke', json={'reason': 'spam'},
                       headers=auth_headers).status_code == 403
    revoked = client.post(f'/api/v1/shares/admin/links/{link_id}/revoke', json={'reason': 'spam'},
                          headers=admin_auth_headers)
    assert revoked.get_json()['link']['revoked_by'] == 'admin'
    assert client.get(f'/api/v1/shares/public/{_token(created)}').status_code == 404

    second = _create(client, auth_headers)
    disabled = client.patch(f'/api/v1/shares/admin/users/{paid_user.id}', json={'sharing_disabled': True},
                            headers=admin_auth_headers)
    assert disabled.status_code == 200
    assert client.get(f'/api/v1/shares/public/{_token(second)}').status_code == 404
    assert _create(client, auth_headers).get_json()['code'] == 'sharing_disabled'


def test_viewers_can_report_a_link(client, paid_user, auth_headers, admin_auth_headers):
    created = _create(client, auth_headers)
    token = _token(created)

    assert client.post(f'/api/v1/shares/public/{token}/report', json={'reason': 'nope'}).status_code == 400
    reported = client.post(f'/api/v1/shares/public/{token}/report',
                           json={'reason': 'spam', 'details': 'x' * 5000})
    assert reported.status_code == 201
    assert len(SharedArtifactReport.query.one().details) == 2000

    listed = client.get('/api/v1/shares/admin/links?reported=1', headers=admin_auth_headers).get_json()
    assert listed['links'][0]['report_count'] == 1


def test_unknown_token_looks_the_same_as_a_revoked_one(client):
    response = client.get('/api/v1/shares/public/not-a-real-token')
    assert response.status_code == 404
    assert response.get_json()['code'] == 'share_unavailable'


def test_admin_can_read_an_accounts_sharing_setting(client, paid_user, auth_headers, admin_auth_headers):
    url = f'/api/v1/shares/admin/users/{paid_user.id}'
    assert client.get(url, headers=auth_headers).status_code == 403
    assert client.get(url, headers=admin_auth_headers).get_json()['sharing_disabled'] is False


def test_limits_can_come_from_the_server_environment(app, monkeypatch):
    from app.sharing import daily_create_limit
    monkeypatch.setenv('SHARE_LINK_DAILY_CREATE_LIMIT', '7')
    with app.app_context():
        assert daily_create_limit() == 7
