"""Turn capture step: capture no longer depends on the reply model choosing a tool.

Every turn runs one forced, structured capture call before the reply. These
tests mock that call (no live AI) and check what is actually persisted, what
the reply model is told, and what the customer sees.
"""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from tests.test_decision_capture import _cards, _seed, _set_history, _call
from tests.test_decision_flow_stabilization import modules


def _response(payload, input_tokens=900, output_tokens=120):
    block = SimpleNamespace(type='tool_use', name='record_turn_capture', input=payload, id='tu_1')
    return SimpleNamespace(content=[block], usage=SimpleNamespace(input_tokens=input_tokens, output_tokens=output_tokens))


def _empty(**overrides):
    payload = {'decisions': [], 'notes': [], 'condition_updates': [], 'outcomes': [], 'lessons': [],
               'task_commitments': [], 'unclear': []}
    payload.update(overrides)
    return payload


@pytest.fixture
def capture_model(monkeypatch):
    """Mock the capture call; records the requests it received."""
    _, agent = modules()
    state = {'payloads': [], 'requests': [], 'error': None}
    monkeypatch.setattr(agent, '_anthropic_api_key', lambda: 'test-key')

    def fake_create(client, *, model_name, **kwargs):
        state['requests'].append({'model': model_name, **kwargs})
        if state['error']:
            raise state['error']
        return _response(state['payloads'].pop(0) if state['payloads'] else _empty()), model_name

    monkeypatch.setattr(agent, '_anthropic_message_create', fake_create)
    return state


def _history(*user_texts, assistant=None, start=None):
    start = start or datetime.utcnow() - timedelta(minutes=10)
    history = []
    for index, text in enumerate(user_texts):
        history.append({'role': 'user', 'content': text, 'timestamp': (start + timedelta(minutes=index * 2)).isoformat()})
        if assistant and index < len(user_texts) - 1:
            history.append({'role': 'assistant', 'content': assistant,
                            'timestamp': (start + timedelta(minutes=index * 2 + 1)).isoformat()})
    return history


def _run(agent, app, user, tid, message):
    with app.test_request_context():
        return agent._run_turn_capture(user=user, user_id=user.id, thread_id=tid, user_message=message)


def test_capture_persists_even_when_the_reply_model_calls_no_tool(app, db, test_user, capture_model):
    from app.models_decision_record import OptionDecision, DecisionSignal

    _, agent = modules()
    tid = 'turn-capture-basic'
    _seed(db, test_user, tid, _cards())
    message = "We're going ahead with Adams and Boulder, Cherry Creek is a no, too much risk. Bid is due Dec 12."
    _set_history(test_user, tid, _history(message))
    capture_model['payloads'].append(_empty(
        decisions=[
            {'message': 1, 'option_key': 'option-a', 'disposition': 'pursue', 'quote': 'going ahead with Adams'},
            {'message': 1, 'option_key': 'option-b', 'disposition': 'pursue', 'quote': 'Boulder'},
            {'message': 1, 'option_key': 'option-c', 'disposition': 'not_pursue', 'quote': 'Cherry Creek is a no',
             'rationale_quote': 'too much risk'},
        ],
        notes=[{'message': 1, 'kind': 'deadline', 'content': 'Bid due', 'quote': 'Bid is due Dec 12', 'date': '2026-12-12'}],
    ))
    capture = _run(agent, app, test_user, tid, message)

    rows = {row.option_key: row for row in OptionDecision.query.all()}
    assert {k: (r.disposition, r.source) for k, r in rows.items()} == {
        'option-a': ('pursue', 'conversation'), 'option-b': ('pursue', 'conversation'),
        'option-c': ('not_pursue', 'conversation'),
    }
    assert DecisionSignal.query.filter_by(kind='deadline').one().structured == {'date': '2026-12-12'}
    assert [s['what'] for s in capture['summary']['saved']] == ['decision', 'decision', 'decision', 'deadline']
    # Forced, structured call with the capture tool only.
    request = capture_model['requests'][0]
    assert request['tool_choice'] == {'type': 'tool', 'name': 'record_turn_capture'}
    assert [tool['name'] for tool in request['tools']] == ['record_turn_capture']
    assert all(action.get('capture_pass') for action in capture['actions'])


def test_reply_model_no_longer_gets_capture_tools(app):
    _, agent = modules()
    names = {tool['name'] for tool in agent._anthropic_tool_definitions(enable_mutation_tools=True, include_capture_tools=False)}
    assert not names & agent._DECISION_CAPTURE_TOOLS
    assert 'generate_execution_plan' in names


def test_missed_capture_is_recovered_from_a_recent_message(app, db, test_user, capture_model):
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'turn-capture-recover'
    _seed(db, test_user, tid, _cards())
    earlier, latest = "We're pursuing Boulder.", "What should we do first?"
    _set_history(test_user, tid, _history(earlier, latest, assistant='Recorded: pursuing Boulder.'))
    capture_model['payloads'].append(_empty(decisions=[
        {'message': 1, 'option_key': 'option-b', 'disposition': 'pursue', 'quote': 'pursuing Boulder'},
    ]))
    _run(agent, app, test_user, tid, latest)
    row = OptionDecision.query.one()
    assert (row.option_key, row.disposition, row.user_quote) == ('option-b', 'pursue', 'pursuing Boulder')


def test_earlier_message_never_overrides_a_later_decision(app, db, test_user, capture_model):
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'turn-capture-stale'
    _seed(db, test_user, tid, _cards())
    earlier, latest = "We're pursuing Boulder.", 'Thanks.'
    _set_history(test_user, tid, _history(earlier, latest, start=datetime.utcnow() - timedelta(hours=2)))
    # A later decision already stands (recorded after the earlier message).
    _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-b', 'disposition': 'not_pursue', 'user_request_quote': 'drop Boulder'},
    ]}, "Let's drop Boulder.")
    capture_model['payloads'].append(_empty(decisions=[
        {'message': 1, 'option_key': 'option-b', 'disposition': 'pursue', 'quote': 'pursuing Boulder'},
    ]))
    capture = _run(agent, app, test_user, tid, latest)
    current = OptionDecision.query.filter_by(superseded_at=None).one()
    assert current.disposition == 'not_pursue'
    assert capture['summary']['already_stored'][0]['reason'] == 'later_decision_stands'


def test_assistant_text_is_never_evidence(app, db, test_user, capture_model):
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'turn-capture-assistant'
    _seed(db, test_user, tid, _cards())
    latest = 'Sounds good.'
    _set_history(test_user, tid, _history('Compare them.', latest, assistant='Recorded: pursuing Adams County Bid.'))
    capture_model['payloads'].append(_empty(decisions=[
        {'message': 2, 'option_key': 'option-a', 'disposition': 'pursue', 'quote': 'pursuing Adams County Bid'},
    ]))
    capture = _run(agent, app, test_user, tid, latest)
    assert OptionDecision.query.count() == 0
    assert capture['summary']['not_saved'][0]['reason'] == 'quote_not_in_customer_message'


def test_repeated_processing_creates_no_duplicates(app, db, test_user, capture_model):
    from app.models_decision_record import DecisionSignal, OptionDecision

    _, agent = modules()
    tid = 'turn-capture-dupes'
    _seed(db, test_user, tid, _cards())
    message = 'Pursue Adams contingent on bonding; we will send the surety letter by 2026-11-13.'
    _set_history(test_user, tid, _history(message))
    payload = _empty(
        decisions=[{'message': 1, 'option_key': 'option-a', 'disposition': 'pursue', 'quote': 'Pursue Adams',
                    'conditions': [{'content': 'Bonding secured', 'quote': 'contingent on bonding'}]}],
        notes=[{'message': 1, 'kind': 'commitment', 'option_key': 'option-a', 'content': 'Surety letter',
                'quote': 'we will send the surety letter by 2026-11-13', 'date': '2026-11-13'}],
    )
    capture_model['payloads'].extend([payload, payload])
    _run(agent, app, test_user, tid, message)
    second = _run(agent, app, test_user, tid, message)
    assert OptionDecision.query.count() == 1
    assert DecisionSignal.query.filter_by(kind='condition').count() == 1
    assert DecisionSignal.query.filter_by(kind='commitment').count() == 1
    assert second['summary']['saved'] == []


def test_condition_change_is_persisted_and_history_kept(app, db, test_user, capture_model):
    from app.decision_capture import decision_facts
    from app.models_decision_record import DecisionSignal

    _, agent = modules()
    tid = 'turn-capture-condition'
    _seed(db, test_user, tid, _cards())
    first = 'Pursue Cherry Creek only if bonding comes through.'
    _set_history(test_user, tid, _history(first))
    capture_model['payloads'].append(_empty(decisions=[
        {'message': 1, 'option_key': 'option-c', 'disposition': 'pursue', 'quote': 'Pursue Cherry Creek',
         'conditions': [{'content': 'Bonding comes through', 'quote': 'only if bonding comes through'}]},
    ]))
    _run(agent, app, test_user, tid, first)
    condition = DecisionSignal.query.filter_by(kind='condition').one()

    latest = 'Good news: the surety came through on the bonding.'
    _set_history(test_user, tid, _history(first, latest, assistant='Great, that is a cleaner path.'))
    capture_model['payloads'].append(_empty(condition_updates=[
        {'message': 2, 'condition_signal_id': str(condition.id), 'status': 'met', 'quote': 'the surety came through'},
    ]))
    capture = _run(agent, app, test_user, tid, latest)
    rows = DecisionSignal.query.filter_by(kind='condition').order_by(DecisionSignal.created_at).all()
    assert [(r.structured['status'], r.retracted_at) for r in rows] == [('open', None), ('met', None)]
    option = {o['option_key']: o for o in decision_facts(test_user, tid)['options']}['option-c']
    assert option['conditions'][0]['status'] == 'met'
    assert capture['summary']['saved'] == [{'what': 'condition_update', 'condition': 'Bonding comes through', 'status': 'met'}]

    capture_model['payloads'].append(_empty(condition_updates=[
        {'message': 2, 'condition_signal_id': option['conditions'][0]['signal_id'], 'status': 'met', 'quote': 'the surety came through'},
    ]))
    again = _run(agent, app, test_user, tid, latest)
    assert DecisionSignal.query.filter_by(kind='condition').count() == 2
    assert again['summary']['already_stored'][0]['what'] == 'condition_update'


def test_change_of_mind_updates_with_history(app, db, test_user, capture_model):
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'turn-capture-change'
    _seed(db, test_user, tid, _cards())
    _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-a', 'disposition': 'pursue', 'user_request_quote': 'Pursue Adams'},
    ]}, 'Pursue Adams.')
    latest = 'Actually we are dropping Adams, the margin is too thin.'
    _set_history(test_user, tid, _history('Pursue Adams.', latest, assistant='Got it.'))
    capture_model['payloads'].append(_empty(decisions=[
        {'message': 2, 'option_key': 'option-a', 'disposition': 'not_pursue', 'quote': 'dropping Adams',
         'rationale_quote': 'the margin is too thin'},
    ]))
    _run(agent, app, test_user, tid, latest)
    rows = OptionDecision.query.order_by(OptionDecision.created_at).all()
    assert [(r.disposition, r.superseded_at is None) for r in rows] == [('pursue', False), ('not_pursue', True)]
    assert rows[1].rationale == 'the margin is too thin'


def test_unclear_reference_saves_nothing_and_shows_option_buttons(app, db, test_user, capture_model):
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'turn-capture-unclear'
    cards = _cards() + [{'id': 'card-d', 'option_key': 'option-d', 'project_name': 'Adams Rail Bid'}]
    _seed(db, test_user, tid, cards)
    latest = "Let's go with the Adams one."
    _set_history(test_user, tid, _history(latest))
    capture_model['payloads'].append(_empty(unclear=[
        {'message': 1, 'reference': 'the Adams one', 'candidate_option_keys': ['option-a', 'option-d']},
    ]))
    capture = _run(agent, app, test_user, tid, latest)
    assert OptionDecision.query.count() == 0
    entries = agent._artifact_entries_from_actions(capture['actions'], user_message=latest)
    status = next(item['artifact']['data'] for item in entries if item['artifact']['type'] == 'status')
    assert status['message'] == "Nothing saved yet: the option wasn't clear."
    assert [a['value'] for a in status['actions']] == ['Adams County Bid', 'Adams Rail Bid']
    # The reply is never withheld for the capture step's results.
    assert agent._apply_option_decision_failure_state('Which Adams bid did you mean', capture['actions']) == (
        'Which Adams bid did you mean', None,
    )


def test_reply_prompt_shows_what_this_turn_saved(app, db, test_user, capture_model):
    _, agent = modules()
    tid = 'turn-capture-facts'
    _seed(db, test_user, tid, _cards())
    message = 'Pursue Boulder.'
    _set_history(test_user, tid, _history(message))
    capture_model['payloads'].append(_empty(decisions=[
        {'message': 1, 'option_key': 'option-b', 'disposition': 'pursue', 'quote': 'Pursue Boulder'},
    ]))
    with app.test_request_context():
        agent._begin_turn_capture(user=test_user, user_id=test_user.id, thread_id=tid, user_message=message,
                                  view_context=None, disable_mutations=False)
        suffix = agent._decision_facts_prompt_suffix(test_user.id, tid)
        agent._end_turn_capture()
        after = agent._decision_facts_prompt_suffix(test_user.id, tid)
    assert '"this_turn":{"saved":[{"what":"decision","option":"Boulder Transit Bid"' in suffix
    assert '"this_turn"' not in after


def test_capture_failure_never_blocks_the_reply(app, db, test_user, capture_model):
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'turn-capture-error'
    _seed(db, test_user, tid, _cards())
    _set_history(test_user, tid, _history('Pursue Boulder.'))
    capture_model['error'] = RuntimeError('provider down')
    capture = _run(agent, app, test_user, tid, 'Pursue Boulder.')
    assert capture['summary'] == {'capture_unavailable': True}
    assert capture['actions'] == [] and OptionDecision.query.count() == 0


def test_no_capture_on_regenerate_or_without_options(app, db, test_user, capture_model):
    _, agent = modules()
    with app.test_request_context():
        assert agent._begin_turn_capture(user=test_user, user_id=test_user.id, thread_id='t', user_message='x',
                                         view_context=None, disable_mutations=True) is None
    tid = 'turn-capture-no-options'
    _seed(db, test_user, tid, [])
    assert _run(agent, app, test_user, tid, 'Pursue it.')['actions'] == []
    assert capture_model['requests'] == []


def test_capture_usage_is_added_to_the_turn(app):
    _, agent = modules()
    merged = agent._merge_capture_usage(
        {'input_tokens': 100, 'output_tokens': 10, 'total_tokens': 110},
        {'usage': {'input_tokens': 50, 'output_tokens': 5, 'model': 'claude-sonnet-5'}},
    )
    assert merged['total_tokens'] == 165 and merged['capture'] == {
        'model': 'claude-sonnet-5', 'input_tokens': 50, 'output_tokens': 5,
    }


def test_conversation_route_runs_capture_before_the_reply(client, db, test_user, auth_headers, monkeypatch, capture_model):
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'turn-capture-route'
    _seed(db, test_user, tid, _cards())
    monkeypatch.setattr(agent, '_resolve_governed_routes',
                        lambda *_a, **_k: ([{'provider': 'anthropic', 'model': 'test-model'}], {}))
    monkeypatch.setattr(agent, '_reserve_preflight_credits', lambda *a, **k: {'ok': True, 'reserved': 0})
    monkeypatch.setattr(agent, '_settle_reserved_credits', lambda *a, **k: {'ok': True, 'charged': 0, 'remaining': 300})
    monkeypatch.setattr(agent, '_persist_credit_deduction', lambda *a, **k: None)
    seen = {}

    def reply_model(user_message, *_args, **kwargs):
        # The reply model runs after capture and sees what was saved.
        seen['rows_before_reply'] = OptionDecision.query.count()
        seen['suffix'] = agent._decision_facts_prompt_suffix(test_user.id, tid)
        return ('Good choice; Boulder fits your crew.',
                {'provider': 'test', 'model': 'test-model', 'input_tokens': 1, 'output_tokens': 1, 'total_tokens': 2},
                [], [], None)

    monkeypatch.setattr(agent, '_generate_assistant_reply_anthropic', reply_model)
    capture_model['payloads'].append(_empty(decisions=[
        {'message': 1, 'option_key': 'option-b', 'disposition': 'pursue', 'quote': 'pursuing Boulder'},
    ]))
    response = client.post('/api/v1/ai-agent/conversation/continue', headers=auth_headers,
                           json={'thread_id': tid, 'message': "We're pursuing Boulder."})
    assert response.status_code == 200, response.get_json()
    payload = response.get_json()
    assert payload['reply'] == 'Good choice; Boulder fits your crew.'
    assert seen['rows_before_reply'] == 1 and '"this_turn"' in seen['suffix']
    assert not [i for i in payload.get('artifact_messages') or [] if i['artifact']['type'] in {'receipts', 'confirm'}]
    assert OptionDecision.query.one().option_key == 'option-b'


# ── Review fixes ───────────────────────────────────────────────────────────


def test_latest_message_wins_within_one_capture(app, db, test_user, capture_model):
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'turn-capture-order'
    _seed(db, test_user, tid, _cards())
    first, latest = "We're pursuing Boulder.", 'Actually drop Boulder.'
    _set_history(test_user, tid, _history(first, latest, assistant='Okay.'))
    capture_model['payloads'].append(_empty(decisions=[
        {'message': 2, 'option_key': 'option-b', 'disposition': 'not_pursue', 'quote': 'drop Boulder'},
        {'message': 1, 'option_key': 'option-b', 'disposition': 'pursue', 'quote': 'pursuing Boulder'},
    ]))
    _run(agent, app, test_user, tid, latest)
    assert [(r.disposition, r.superseded_at is None) for r in OptionDecision.query.all()] == [('not_pursue', True)]


def test_earlier_condition_update_never_overturns_a_later_status(app, db, test_user, capture_model):
    from app.models_decision_record import DecisionSignal

    _, agent = modules()
    tid = 'turn-capture-condition-stale'
    _seed(db, test_user, tid, _cards())
    start = datetime.utcnow() - timedelta(hours=1)
    msgs = ['Pursue Cherry Creek if bonding comes through.', 'Bonding came through.', 'Bonding fell through after all.']
    _set_history(test_user, tid, _history(*msgs, assistant='Noted.', start=start))
    _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-c', 'disposition': 'pursue', 'user_request_quote': 'Pursue Cherry Creek',
         'conditions': [{'content': 'Bonding', 'user_quote': 'if bonding comes through'}]},
    ]}, msgs[0])
    open_row = DecisionSignal.query.filter_by(kind='condition').one()
    _call(agent, test_user, tid, 'record_decision_context', {
        'kind': 'condition', 'condition_signal_id': str(open_row.id), 'structured': {'status': 'not_met'},
        'user_request_quote': 'Bonding fell through',
    }, msgs[2])
    current = DecisionSignal.query.filter_by(kind='condition', supersedes_id=str(open_row.id)).one()
    capture_model['payloads'].append(_empty(condition_updates=[
        {'message': 2, 'condition_signal_id': str(current.id), 'status': 'met', 'quote': 'Bonding came through'},
    ]))
    capture = _run(agent, app, test_user, tid, 'What now?')
    statuses = [r.structured['status'] for r in DecisionSignal.query.filter_by(kind='condition').order_by(DecisionSignal.created_at)]
    assert statuses == ['open', 'not_met']
    assert capture['summary']['already_stored'][0]['reason'] == 'later_status_stands'


def test_reworded_quote_from_the_same_statement_is_not_a_duplicate(app, db, test_user, capture_model):
    from app.models_decision_record import DecisionSignal

    _, agent = modules()
    tid = 'turn-capture-reworded'
    _seed(db, test_user, tid, _cards())
    message = 'We worry the crew is stretched thin this winter.'
    _set_history(test_user, tid, _history(message))
    capture_model['payloads'].extend([
        _empty(notes=[{'message': 1, 'kind': 'concern', 'content': 'Crew capacity', 'quote': 'crew is stretched thin'}]),
        _empty(notes=[{'message': 1, 'kind': 'concern', 'content': 'Crew stretched thin in winter',
                       'quote': 'the crew is stretched thin this winter'}]),
    ])
    _run(agent, app, test_user, tid, message)
    _run(agent, app, test_user, tid, message)
    assert DecisionSignal.query.filter_by(kind='concern').count() == 1


def test_outcome_is_not_duplicated_after_a_new_decision_row(app, db, test_user, capture_model):
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'turn-capture-outcome-dupe'
    _seed(db, test_user, tid, _cards())
    _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-a', 'disposition': 'pursue', 'user_request_quote': 'Pursue Adams'},
    ]}, 'Pursue Adams.')
    message = 'We won Adams and margin came in at 18 percent against 20 expected.'
    _set_history(test_user, tid, _history(message))
    outcome = {'message': 1, 'option_key': 'option-a', 'status': 'partially_achieved', 'summary': 'Won, margin below plan',
               'quote': 'We won Adams', 'observed': '18 percent', 'expected': '20'}
    capture_model['payloads'].append(_empty(outcomes=[outcome]))
    _run(agent, app, test_user, tid, message)
    _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-a', 'disposition': 'still_evaluating', 'user_request_quote': 'reconsidering Adams'},
    ]}, 'We are reconsidering Adams.')
    capture_model['payloads'].append(_empty(outcomes=[{**outcome, 'quote': 'won Adams and margin came in at 18 percent'}]))
    _run(agent, app, test_user, tid, message)
    entries = [e for row in OptionDecision.query.all() for e in (row.outcomes or [])]
    assert len(entries) == 1
    assert (entries[0].get('observed_result'), entries[0].get('expected_result')) == ('18 percent', '20')


def test_aware_timestamp_never_disables_capture(app, db, test_user, capture_model):
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'turn-capture-aware'
    _seed(db, test_user, tid, _cards())
    _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-a', 'disposition': 'pursue', 'user_request_quote': 'Pursue Adams'},
    ]}, 'Pursue Adams.')
    history = [
        {'role': 'user', 'content': 'Drop Adams.', 'timestamp': '2026-01-01T10:00:00+00:00'},
        {'role': 'user', 'content': 'And pursue Boulder.', 'timestamp': datetime.utcnow().isoformat()},
    ]
    _set_history(test_user, tid, history)
    capture_model['payloads'].append(_empty(decisions=[
        {'message': 1, 'option_key': 'option-a', 'disposition': 'not_pursue', 'quote': 'Drop Adams'},
        {'message': 2, 'option_key': 'option-b', 'disposition': 'pursue', 'quote': 'pursue Boulder'},
    ]))
    _run(agent, app, test_user, tid, 'And pursue Boulder.')
    current = {r.option_key: r.disposition for r in OptionDecision.query.filter_by(superseded_at=None)}
    assert current == {'option-a': 'pursue', 'option-b': 'pursue'}


def test_new_reason_on_unchanged_decision_is_saved_without_a_new_decision_row(app, db, test_user, capture_model):
    from app.models_decision_record import DecisionSignal, OptionDecision

    _, agent = modules()
    tid = 'turn-capture-new-reason'
    _seed(db, test_user, tid, _cards())
    _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-b', 'disposition': 'pursue', 'user_request_quote': 'Pursue Boulder'},
    ]}, 'Pursue Boulder.')
    message = 'Still pursuing Boulder because the client renewed. Only if the permit clears.'
    _set_history(test_user, tid, _history(message))
    capture_model['payloads'].append(_empty(decisions=[
        {'message': 1, 'option_key': 'option-b', 'disposition': 'pursue', 'quote': 'Still pursuing Boulder',
         'rationale_quote': 'because the client renewed',
         'conditions': [{'content': 'Permit clears', 'quote': 'Only if the permit clears'}]},
    ]))
    capture = _run(agent, app, test_user, tid, message)
    assert OptionDecision.query.count() == 1
    assert DecisionSignal.query.filter_by(kind='rationale').one().user_quote == 'because the client renewed'
    assert DecisionSignal.query.filter_by(kind='condition').one().structured['status'] == 'open'
    assert {item['what'] for item in capture['summary']['saved']} == {'rationale', 'condition'}


def test_unclear_needs_the_latest_message_and_real_candidates(app, db, test_user, capture_model):
    _, agent = modules()
    tid = 'turn-capture-unclear-rules'
    _seed(db, test_user, tid, _cards())
    _set_history(test_user, tid, _history('Go with the Adams one.', 'Adams County, sorry.', assistant='Which one?'))
    capture_model['payloads'].append(_empty(unclear=[
        {'message': 1, 'reference': 'the Adams one', 'candidate_option_keys': ['option-a', 'option-b']},
        {'message': 2, 'reference': 'Adams County', 'candidate_option_keys': []},
    ]))
    capture = _run(agent, app, test_user, tid, 'Adams County, sorry.')
    assert capture['summary']['unclear'] == []
    assert not [e for e in agent._artifact_entries_from_actions(capture['actions'], user_message='x')
                if e['artifact']['type'] == 'status']


def test_billing_prices_each_call_at_its_own_model(app):
    _, agent = modules()
    merged = agent._merge_capture_usage(
        {'model': 'claude-haiku-4-5', 'input_tokens': 100, 'output_tokens': 10, 'total_tokens': 110},
        {'usage': {'input_tokens': 50, 'output_tokens': 5, 'model': 'claude-sonnet-5'}},
    )
    assert merged['component_usages'] == [
        {'model': 'claude-haiku-4-5', 'input_tokens': 100, 'output_tokens': 10, 'role': 'reply'},
        {'model': 'claude-sonnet-5', 'input_tokens': 50, 'output_tokens': 5, 'role': 'capture'},
    ]


def test_one_condition_is_stored_once_and_never_as_a_reason(app, db, test_user, capture_model):
    from app.models_decision_record import DecisionSignal

    _, agent = modules()
    tid = 'turn-capture-condition-once'
    _seed(db, test_user, tid, _cards())
    _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-c', 'disposition': 'pursue', 'user_request_quote': 'Pursue Cherry Creek'},
    ]}, 'Pursue Cherry Creek.')
    message = 'Cherry Creek only if we can line up bonding by Dec 1. Surety letter for Adams by Friday.'
    quote = 'Cherry Creek only if we can line up bonding by Dec 1'
    _set_history(test_user, tid, _history(message))
    capture_model['payloads'].append(_empty(
        decisions=[{'message': 1, 'option_key': 'option-c', 'disposition': 'pursue', 'quote': quote,
                    'rationale_quote': quote,
                    'conditions': [{'content': 'Bonding lined up', 'quote': quote, 'due_by': '2026-12-01'}]}],
        notes=[
            {'message': 1, 'kind': 'condition', 'option_key': 'option-c', 'content': 'Pursuit conditional on bonding',
             'quote': quote, 'due_by': '2026-12-01'},
            {'message': 1, 'kind': 'rationale', 'option_key': 'option-c', 'content': quote, 'quote': quote},
            {'message': 1, 'kind': 'commitment', 'option_key': 'option-a', 'content': 'Surety letter',
             'quote': 'Surety letter for Adams by Friday', 'due_by': '2026-11-13'},
        ],
    ))
    _run(agent, app, test_user, tid, message)
    assert DecisionSignal.query.filter_by(kind='condition').count() == 1
    assert DecisionSignal.query.filter_by(kind='rationale').count() == 0
    assert DecisionSignal.query.filter_by(kind='commitment').one().structured == {'date': '2026-11-13'}
