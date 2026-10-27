"""One-pager report: decision content in the shared copy and owner presentation edits."""

import pytest
from app.models import SharedArtifact
from app.routes.sessions import save_user_sessions
from app.scorecards import upsert_scorecard
from app.sharing import (
    PUBLIC_RESPONSE_FIELDS,
    PUBLIC_SNAPSHOT_FIELDS,
    disclosure_narrative_matches,
    filter_public_snapshot,
    sanitize_presentation,
    sanitize_scorecard,
)


def test_exports_keep_gate_criteria_out_of_scored_dimension_rows(app):
    from app.routes.export import _scorecard_component_rows

    rows = _scorecard_component_rows({
        'rubric': {'criteria': [
            {'key': 'fit', 'label': 'Fit', 'weight': 1.0},
            {'key': 'bonding', 'label': 'Bonding available', 'gate': True},
        ]},
        'dimensions': {
            'fit': {'score': 72, 'label': 'Fit'},
            'bonding': {'score': 0, 'label': 'Bonding available'},
        },
        'gates': [{'key': 'bonding', 'status': 'fail'}],
    })
    assert [row['key'] for row in rows] == ['fit']

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
        'executive_summary': 'The contract is worth $2.4M and merits review.',
        'top_risks': [{'risk': 'The expected margin is 18 percent.', 'mitigation': 'Review in 2026.'}],
        'financial_impact': {'potential_loss': 2400000},
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
    payload = {
        'artifact_type': 'scorecard', 'thread_id': THREAD, 'scorecard_id': 'report-card-a',
        'disclosure_settings': {
            'include_facts': True,
            'fact_keys': ['contract_value', 'surety_status'],
            'include_metrics': True,
            'include_financials': True,
        },
        **extra,
    }
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


def test_new_link_defaults_exclude_facts_metrics_and_financials(client, paid_user, auth_headers):
    preview = client.post('/api/v1/shares/preview', json={
        'artifact_type': 'scorecard', 'thread_id': THREAD, 'scorecard_id': 'report-card-a',
    }, headers=auth_headers).get_json()
    card = preview['snapshot']['scorecard']
    assert 'facts' not in card
    assert 'metrics' not in card
    assert 'financial_impact' not in card
    assert preview['disclosure_review']['required'] is True
    matches = preview['disclosure_review']['matches']
    assert any(item['path'].endswith('executive_summary') and item['excluded_field'] == 'facts.contract_value' for item in matches)
    assert any('top_risks' in item['path'] and item['excluded_field'] == 'facts.contract_value' for item in matches) is False
    assert any('top_risks' in item['path'] and item['excluded_value'] == 18 for item in matches) is False


def test_per_link_fact_selection_and_preview_equal_recipient_payload(client, paid_user, auth_headers):
    settings = {
        'include_facts': True, 'fact_keys': ['surety_status'],
        'include_metrics': False, 'include_financials': False,
    }
    request_body = {
        'artifact_type': 'scorecard', 'thread_id': THREAD, 'scorecard_id': 'report-card-a',
        'disclosure_settings': settings, 'disclosure_review_confirmed': True,
    }
    preview = client.post('/api/v1/shares/preview', json=request_body, headers=auth_headers).get_json()
    created = client.post('/api/v1/shares', json=request_body, headers=auth_headers)
    token = created.get_json()['link']['url'].rsplit('/', 1)[-1]
    public = client.get(f'/api/v1/shares/public/{token}').get_json()
    assert public['snapshot'] == preview['snapshot']
    assert set(public['snapshot']['scorecard']['facts']) == {'surety_status'}
    assert SharedArtifact.query.filter_by(token=token).one().disclosure_reviewed_at is not None


def test_existing_snapshot_is_filtered_at_read_time(client, db, paid_user):
    link = SharedArtifact(
        token='legacy-protective-share', owner_user_id=paid_user.id, thread_id=THREAD,
        artifact_type='scorecard', source_id='report-card-a', title='Legacy',
        snapshot_json={'scorecard': sanitize_scorecard(_card('report-card-a', 'Denver'), include_evidence=False, public_id='c1')},
        include_evidence=False, disclosure_settings={},
    )
    db.session.add(link)
    db.session.commit()
    card = client.get('/api/v1/shares/public/legacy-protective-share').get_json()['snapshot']['scorecard']
    assert 'facts' not in card and 'metrics' not in card and 'financial_impact' not in card


def test_hidden_section_is_removed_server_side_and_public_allowlists_are_fixed():
    raw = {
        'scorecard': {'id': 'c1', 'jaspen_score': 70, 'dimensions': {'fit': {'score': 70}}, 'metrics': {'x': 1}},
        'presentation': {'layout': {'hidden': ['criteria']}},
    }
    filtered = filter_public_snapshot(raw, {'include_metrics': True})
    assert 'dimensions' not in filtered['scorecard']
    assert set(filtered) <= PUBLIC_SNAPSHOT_FIELDS
    assert PUBLIC_RESPONSE_FIELDS == {
        'artifact_type', 'title', 'created_at', 'expires_at', 'include_evidence',
        'disclosure_settings', 'snapshot',
    }


def test_narrative_check_flags_only_values_excluded_for_this_link():
    raw = {'scorecard': {
        'executive_summary': 'Contract value is $2.4M; score is 72 for the 2026 review.',
        'top_risks': [{'risk': 'Margin is 18 percent.'}],
        'facts': {
            'contract_value': {'value': 2400000, 'unit': 'USD'},
            'margin_pct': {'value': 18, 'unit': 'percent'},
        },
        'jaspen_score': 72,
    }}
    settings = {'include_facts': False, 'include_metrics': False, 'include_financials': False}
    filtered = filter_public_snapshot(raw, settings)
    matches = disclosure_narrative_matches(raw, filtered, settings)
    assert {(item['excluded_value'], item['path']) for item in matches} == {
        (2400000, 'scorecard.executive_summary'),
        (18, 'scorecard.top_risks.0.risk'),
    }
    opted_in = {'include_facts': True, 'fact_keys': ['contract_value', 'margin_pct']}
    assert disclosure_narrative_matches(raw, filter_public_snapshot(raw, opted_in), opted_in) == []


def test_presentation_wording_cannot_bypass_excluded_value_review():
    raw = {
        'scorecard': {
            'facts': {'contract_value': {'value': 2400000, 'unit': 'USD'}},
            'jaspen_score': 72,
        },
        'presentation': {'text': {'headline': 'Approve the $2.4M contract'}},
    }
    settings = {'include_facts': False, 'include_metrics': False, 'include_financials': False}
    filtered = filter_public_snapshot(raw, settings)

    assert filtered['presentation']['text']['headline'] == 'Approve the $2.4M contract'
    assert disclosure_narrative_matches(raw, filtered, settings) == [{
        'path': 'presentation.text.headline',
        'excluded_field': 'facts.contract_value',
        'excluded_value': 2400000,
    }]


def test_empty_fact_selection_means_no_facts_are_shared_or_exempt_from_review():
    raw = {'scorecard': {
        'executive_summary': 'Contract is $2.4M.',
        'facts': {'contract_value': {'value': 2400000, 'unit': 'USD'}},
    }}
    settings = {'include_facts': True, 'fact_keys': []}

    filtered = filter_public_snapshot(raw, settings)
    matches = disclosure_narrative_matches(raw, filtered, settings)

    assert 'facts' not in filtered['scorecard']
    assert [(item['excluded_field'], item['excluded_value']) for item in matches] == [
        ('facts.contract_value', 2400000),
    ]


def test_financial_review_checks_amounts_and_rates_without_duration_or_text_noise():
    raw = {'scorecard': {
        'executive_summary': 'Payback in 3 years; High confidence. NPV is $1.2M.',
        'investment_analysis': {
            'payback_years': 3,
            'confidence': 'High',
        },
        'npv_irr_analysis': {
            'npv_3_year': 1200000,
        },
    }}
    settings = {'include_financials': False}

    matches = disclosure_narrative_matches(
        raw,
        filter_public_snapshot(raw, settings),
        settings,
    )

    assert [(item['excluded_field'], item['excluded_value']) for item in matches] == [
        ('npv_irr_analysis.npv_3_year', 1200000),
    ]


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
    # The web client's JSON helper sends PATCH; both verbs save.
    cleared = client.patch(f'/api/v1/shares/manage/{token}/presentation',
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


def test_owner_branding_slots_are_accepted_and_limited():
    clean = sanitize_presentation({'text': {
        'brand_name': 'ACME BUILDERS', 'company_name': 'Acme Builders, Inc.',
        'report_label': 'Q4 BID REVIEW', 'tagline': '',
    }})
    assert clean == {'text': {
        'brand_name': 'ACME BUILDERS', 'company_name': 'Acme Builders, Inc.', 'report_label': 'Q4 BID REVIEW',
    }}
    with pytest.raises(ValueError):
        sanitize_presentation({'text': {'brand_name': 'x' * 61}})


def test_workspace_saves_report_edits_on_the_scorecard_and_shares_inherit_them(client, paid_user, auth_headers):
    url = f'/api/v1/strategy/threads/{THREAD}/scorecards/report-card-a/overrides'
    saved = client.patch(url, json={'report_presentation': {
        'text': {'brand_name': 'ACME BUILDERS'}, 'colors': {'accent': '#0f6e77'},
    }}, headers=auth_headers)
    assert saved.status_code == 200, saved.get_json()

    rejected = client.patch(url, json={'report_presentation': {'colors': {'accent': '#ffffff'}}}, headers=auth_headers)
    assert rejected.status_code == 400
    assert rejected.get_json()['code'] == 'low_contrast'

    token = _share(client, auth_headers)
    snapshot = client.get(f'/api/v1/shares/public/{token}').get_json()['snapshot']
    assert snapshot['presentation'] == {'colors': {'accent': '#0F6E77'}, 'text': {'brand_name': 'ACME BUILDERS'}}



def _shared_presentation(overrides):
    from app.sharing import ARTIFACT_SCORECARD, build_snapshot

    card = {**_card('report-card-a', 'Denver Water'), 'display_overrides': overrides}
    snapshot, *_ = build_snapshot(artifact_type=ARTIFACT_SCORECARD, cards=[card],
                                  include_evidence=False, scorecard_id='report-card-a')
    return snapshot.get('presentation')


def test_shared_one_pager_uses_a_chat_brand_color_when_the_report_has_no_accent():
    assert _shared_presentation({'accent_color': '#0a66c2'}) == {'colors': {'accent': '#0A66C2'}}
    # The report's own accent wins; other edits are kept.
    assert _shared_presentation({
        'accent_color': '#0a66c2',
        'report_presentation': {'colors': {'accent': '#0f6e77', 'tint': '#eef5f7'}, 'text': {'brand_name': 'ACME'}},
    }) == {'colors': {'accent': '#0F6E77', 'tint': '#EEF5F7'}, 'text': {'brand_name': 'ACME'}}
    assert _shared_presentation({
        'accent_color': '#0a66c2', 'report_presentation': {'text': {'brand_name': 'ACME'}},
    }) == {'colors': {'accent': '#0A66C2'}, 'text': {'brand_name': 'ACME'}}
    # Unreadable or malformed colors fall back to the default accent.
    assert _shared_presentation({'accent_color': '#ffff00'}) is None
    assert _shared_presentation({'accent_color': 'blue'}) is None

def test_rereading_a_card_keeps_fact_resolved_gates():
    from app.decision_processing import apply_decision_kit

    card = {
        'project_name': 'Denver',
        'decision_kit': 'rfp_bid',
        'attributes': {
            'surety_status': {'value': 'confirmed', 'source': 'user', 'evidence': 'surety confirmed'},
            'submission_due': {'value': '2099-11-20', 'source': 'user', 'evidence': 'due November 20, 2099'},
        },
        # As stored: gate criteria without the kit's fact bindings.
        'scoring_rubric': {'status': 'approved', 'criteria': [
            {'key': 'submission_deadline', 'label': 'Able to submit by deadline', 'gate': True, 'weight': 0},
            {'key': 'surety_confirmation', 'label': 'Surety / bond confirmation', 'gate': True, 'weight': 0},
        ]},
        'gates': [],
    }
    reread = apply_decision_kit(card, decision_kit='rfp_bid')
    assert {g['key']: g['status'] for g in reread['gates']} == {
        'submission_deadline': 'pass', 'surety_confirmation': 'pass',
    }
