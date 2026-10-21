"""Group D: the AI's data answers stand, results show as a table card, empty turns are status."""
import sys
import types


def _agent():
    return sys.modules['app.routes.ai_agent']


def test_snowflake_results_become_a_table_card(app, monkeypatch):
    agent = _agent()
    fake = types.ModuleType('app.snowflake_insights')
    fake.run_allowlisted_query = lambda **kwargs: {
        'rows': [{'REGION': 'West', 'REVENUE': 1250000}, {'REGION': 'East', 'REVENUE': 980000}],
        'query': 'SELECT ...', 'summary': {'used_columns': ['REGION', 'REVENUE']},
    }
    monkeypatch.setitem(sys.modules, 'app.snowflake_insights', fake)
    monkeypatch.setattr(agent, '_snowflake_allowlist', lambda user_id: ['sales.regions'])
    monkeypatch.setattr(agent, '_resolve_snowflake_table', lambda table, allowlist, intent: 'sales.regions')

    result = agent._execute_connector_query_tool('u1', {'connector_type': 'snowflake', 'table': 'sales.regions'})

    card = result['artifact']
    assert card['type'] == 'data_table'
    assert card['data']['columns'] == ['REGION', 'REVENUE']
    assert card['data']['rows'][0] == {'REGION': 'West', 'REVENUE': 1250000}
    assert card['data']['returned_rows'] == 2
    entries = agent._artifact_entries_from_actions([{'tool': 'query_connector_data', 'result': result}])
    assert [entry['artifact']['type'] for entry in entries] == ['data_table']


def test_an_empty_turn_with_nothing_done_is_a_status_card_not_a_canned_question(app):
    agent = _agent()
    reply = agent._finalize_agent_reply('', '', [], user_id='u', thread_id='t', executed_actions=[])
    assert reply == ''
    entries = agent._artifact_entries_from_actions([], user_message='What should I do next?', reply=reply)
    card = entries[0]['artifact']
    assert card['type'] == 'status' and card['data']['tone'] == 'error'
    assert card['data']['retry_message'] == 'What should I do next?'


def test_a_reply_with_content_gets_no_status_card(app):
    agent = _agent()
    assert agent._artifact_entries_from_actions([], user_message='hi', reply='Hello there.') == []


def test_the_data_override_and_keyword_helpers_are_gone():
    agent = _agent()
    for name in (
        '_enforce_connector_data_reply', '_direct_connector_fallback_reply', '_message_has_data_context_request',
        '_infer_connector_query_params_from_message', '_looks_like_connector_deferral', '_fallback_reply_for_turn',
    ):
        assert not hasattr(agent, name), name
