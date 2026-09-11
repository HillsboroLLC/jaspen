from app import db as app_db
from app.decision_records import accept_exposure
from app.models_decision_record import DecisionRecord


def _record(user):
    record = DecisionRecord(
        user_id=user.id,
        thread_id='acceptance-thread',
        title='Warehouse decision',
        record={
            'scorecards': [{
                'id': 'option-a',
                'name': 'Phased automation',
                'evidence_profile': {
                    'criteria': [{
                        'key': 'financial_viability',
                        'label': 'Financial viability',
                        'confidence': 'assumed',
                        'weight': 0.25,
                        'score': 45,
                        'swing': 8.75,
                        'severity': 'material',
                        'evidenced': False,
                        'resolution': 'Upload the supplier quote.',
                    }],
                },
                'top_risks': [{
                    'id': 'risk-1',
                    'risk': 'Cutover interrupts operations',
                    'probability': 'Medium',
                    'impact_dollars': 500000,
                    'mitigation': 'Stage the cutover.',
                    'residual_risk': 'Low',
                }],
            }],
        },
    )
    app_db.session.add(record)
    app_db.session.commit()
    return record


def test_acceptance_is_an_attributed_append_only_server_snapshot(db, test_user):
    record = _record(test_user)
    entry, created = accept_exposure(
        record,
        test_user,
        kind='criterion',
        option_name='option-a',
        target_key='financial_viability',
        note='Proceeding while the quote is finalized.',
    )

    assert created is True
    assert entry['accepted_by'] == {
        'user_id': test_user.id,
        'name': test_user.name,
        'email': test_user.email,
    }
    assert entry['accepted_at']
    assert entry['note'] == 'Proceeding while the quote is finalized.'
    assert entry['exposure']['exposure_points'] == 8.75
    assert entry['exposure']['confidence'] == 'assumed'

    same, created_again = accept_exposure(
        record,
        test_user,
        kind='criterion',
        option_name='Phased automation',
        target_key='financial_viability',
    )
    assert created_again is False
    assert same['id'] == entry['id']
    assert len(record.accepted_exposures) == 1


def test_only_a_real_current_exposure_can_be_accepted(db, test_user):
    record = _record(test_user)
    payload = {**record.record}
    payload['scorecards'] = [{**payload['scorecards'][0]}]
    payload['scorecards'][0]['evidence_profile'] = {
        **payload['scorecards'][0]['evidence_profile'],
        'criteria': [{**payload['scorecards'][0]['evidence_profile']['criteria'][0]}],
    }
    profile = payload['scorecards'][0]['evidence_profile']['criteria'][0]
    profile.update({'confidence': 'high', 'evidenced': True, 'swing': 0})
    record.record = payload
    app_db.session.commit()

    try:
        accept_exposure(
            record,
            test_user,
            kind='criterion',
            option_name='option-a',
            target_key='financial_viability',
        )
    except ValueError as exc:
        assert 'unresolved criterion exposure' in str(exc)
    else:
        raise AssertionError('A fully evidenced, zero-exposure criterion was accepted')


def test_residual_risk_acceptance_records_the_mitigation_assumption(db, test_user):
    record = _record(test_user)
    entry, created = accept_exposure(
        record,
        test_user,
        kind='risk',
        option_name='option-a',
        target_key='risk-1',
    )

    assert created is True
    assert entry['exposure'] == {
        'kind': 'risk',
        'option_id': 'option-a',
        'option_name': 'Phased automation',
        'target_key': 'risk-1',
        'target_label': 'Cutover interrupts operations',
        'likelihood': 'Medium',
        'impact': 500000,
        'mitigation': 'Stage the cutover.',
        'residual_risk': 'Low',
    }


def test_endpoint_ignores_client_authorship_and_numeric_claims(
    client, db, test_user, auth_headers, monkeypatch,
):
    record = _record(test_user)
    monkeypatch.setattr(
        'app.routes.decision_records.create_or_refresh_record',
        lambda user, thread_id: (record, False),
    )

    response = client.post(
        '/api/v1/decision-records/from-thread/acceptance-thread/accepted-exposures',
        headers=auth_headers,
        json={
            'kind': 'criterion',
            'option_name': 'option-a',
            'target_key': 'financial_viability',
            'note': 'Known and accepted.',
            'accepted_by': {'name': 'Not the signed-in user'},
            'exposure_points': 0,
            'confidence': 'high',
        },
    )

    assert response.status_code == 201
    entry = response.get_json()['accepted_exposure']
    assert entry['accepted_by']['user_id'] == test_user.id
    assert entry['accepted_by']['name'] == test_user.name
    assert entry['exposure']['exposure_points'] == 8.75
    assert entry['exposure']['confidence'] == 'assumed'


def test_listing_is_owner_scoped_and_empty_before_acceptance(
    client, db, test_user, auth_headers,
):
    response = client.get(
        '/api/v1/decision-records/from-thread/not-recorded/accepted-exposures',
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.get_json() == {'accepted_exposures': []}
