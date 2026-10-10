"""One-pager report: decision content in the shared copy and owner presentation edits."""

import pytest

from app.models import SharedArtifact
from app.routes.sessions import save_user_sessions
from app.scorecards import upsert_scorecard
from app.sharing import sanitize_presentation, sanitize_scorecard


THREAD = 'report-thread'
QUOTE = 'our surety has confirmed the bonding'


def _card(card_id, name, score=64):
    return {
        'id': card_id,
        'analysis_id': card_id,
        'project_name': name,
        'jaspen_score': score,
        'thread_id': THREAD,
        'decision_kit': 'rfp_bid',
        'recommendation': {'label': 'Bid', 'trace': [{'step': 'score', 'value': score, 'effect': 'meets'}]},
        'metrics': {'expected_value': {'value': 151200, 'label': 'Expected margin',
                                       'inputs': {'contract_value': {'value': 2400000, 'evidence': QUOTE}}}},
        'gates': [{'key': 'surety_confirmation', 'label': 'Surety / bond confirmation', 'status': 'pass',
                   'evidence': QUOTE}],
        'decision_state': {
            'facts': {
                'contract_value': {'value': 2400000, 'unit': 'USD', 'source': 'user', 'evidence': 'contract value $2,400,000'},
                'surety_status': {'value': 'confirmed', 'source': 'user', 'evidence': QUOTE},
                'empty_fact': {'value': ''},
            },
            'option_identity': 'opt_secret',
        },
    }


def _session():
    return {
        'session_id': THREAD,
        'name': 'Which RFPs should we bid on?',
        'status': 'in_progress',
        'chat_history': [],
        'result': {},
        'scorecard_queue': [],
        'strategy_objective': 'speed',
        'decision_kit': 'rfp_bid',
    }


@pytest.fixture
def paid_user(db, test_user):
    test_user.subscription_plan = 'starter'
    test_user.subscription_status = 'active'
    db.session.commit()
    save_user_sessions(test_user.id, {THREAD: _session()})
    upsert_scorecard(user_id=test_user.id, thread_id=THREAD, payload=_card('report-card-a', 'Denver Water pump station'))
    db.session.commit()
    yield test_user
    # Other sharing tests count links globally; leave none behind.
    SharedArtifact.query.filter_by(thread_id=THREAD).delete()
    db.session.commit()


def _share(client, headers, **extra):
    payload = {'artifact_type': 'scorecard', 'thread_id': THREAD, 'scorecard_id': 'report-card-a', **extra}
    response = client.post('/api/v1/shares', json=payload, headers=headers)
    assert response.status_code == 201, response.get_json()
    return response.get_json()['link']['url'].rsplit('/', 1)[-1]


def test_shared_copy_carries_code_owned_decision_content_without_quotes():
    shared = sanitize_scorecard(_card('report-card-a', 'Denver'), include_evidence=False, public_id='c1')

    assert shared['recommendation']['label'] == 'Bid'
    assert shared['metrics']['expected_value']['value'] == 151200
    assert shared['gates'][0]['status'] == 'pass'
    assert shared['decision_kit'] == 'rfp_bid'
    assert shared['facts']['contract_value'] == {'value': 2400000, 'unit': 'USD', 'source': 'user'}
    assert 'empty_fact' not in shared['facts']
    assert 'decision_state' not in shared
    assert QUOTE not in str(shared)


def test_fact_wording_is_shared_only_when_evidence_is_included():
    shared = sanitize_scorecard(_card('report-card-a', 'Denver'), include_evidence=True, public_id='c1')
    assert shared['facts']['surety_status']['evidence'] == QUOTE


def test_snapshot_includes_report_context(client, paid_user, auth_headers):
    token = _share(client, auth_headers)
    snapshot = client.get(f'/api/v1/shares/public/{token}').get_json()['snapshot']
    assert snapshot['context'] == {'strategy_objective': 'speed', 'decision_kit': 'rfp_bid'}


def test_owner_can_load_and_save_presentation(client, paid_user, auth_headers):
    token = _share(client, auth_headers)

    manage = client.get(f'/api/v1/shares/manage/{token}', headers=auth_headers)
    assert manage.status_code == 200
    assert manage.get_json()['owner'] is True
    assert manage.get_json()['can_edit'] is True

    edits = {
        'colors': {'accent': '#0f6e77'},
        'text': {'headline': 'Should we bid on Denver Water?', 'score': '99'},
        'layout': {'hidden': ['takeaways'], 'evidence_variant': 'compact'},
    }
    saved = client.put(f'/api/v1/shares/manage/{token}/presentation',
                       json={'presentation': edits}, headers=auth_headers)
    assert saved.status_code == 200
    presentation = saved.get_json()['presentation']
    assert presentation == {
        'colors': {'accent': '#0F6E77'},
        'text': {'headline': 'Should we bid on Denver Water?'},
        'layout': {'hidden': ['takeaways'], 'evidence_variant': 'compact'},
    }

    public = client.get(f'/api/v1/shares/public/{token}').get_json()['snapshot']
    assert public['presentation'] == presentation
    # Numbers are untouched by presentation edits.
    assert public['scorecard']['jaspen_score'] == 64
    assert public['scorecard']['metrics']['expected_value']['value'] == 151200


def test_clearing_edits_removes_presentation(client, paid_user, auth_headers):
    token = _share(client, auth_headers)
    client.put(f'/api/v1/shares/manage/{token}/presentation',
               json={'presentation': {'text': {'headline': 'X'}}}, headers=auth_headers)
    cleared = client.put(f'/api/v1/shares/manage/{token}/presentation',
                         json={'presentation': {}}, headers=auth_headers)
    assert cleared.status_code == 200
    link = SharedArtifact.query.filter_by(token=token).first()
    assert 'presentation' not in link.snapshot_json


def test_unknown_link_is_not_manageable(client, paid_user, auth_headers):
    assert client.get('/api/v1/shares/manage/not-a-token', headers=auth_headers).status_code == 404
    response = client.put('/api/v1/shares/manage/not-a-token/presentation',
                          json={'presentation': {}}, headers=auth_headers)
    assert response.status_code == 404


@pytest.mark.parametrize('payload, code', [
    ({'colors': {'accent': 'red'}}, 'invalid_colors'),
    ({'colors': {'accent': '#FFEEEE'}}, 'low_contrast'),
    ({'text': {'headline': 'x' * 201}}, 'text_too_long'),
    ({'text': {'headline': 5}}, 'invalid_text'),
    ({'layout': {'hidden': ['scores']}}, 'invalid_layout'),
    ({'layout': {'order': ['standings']}}, 'invalid_layout'),
    ({'layout': {'evidence_variant': 'huge'}}, 'invalid_layout'),
    ('not an object', 'invalid_presentation'),
])
def test_presentation_validation_rejects_unsafe_edits(payload, code):
    with pytest.raises(ValueError) as error:
        sanitize_presentation(payload)
    assert str(error.value) == code


def test_tint_may_be_light_because_it_never_carries_text():
    assert sanitize_presentation({'colors': {'tint': '#eef5f7'}}) == {'colors': {'tint': '#EEF5F7'}}
