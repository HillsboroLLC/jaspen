"""Phase 1: the AI captures decision intent and metadata; code stores only facts.

Mocked model only. These tests exercise the capture tools directly and through
the conversation route, the facts block the AI sees, and the rule that no tool
result carries customer-facing wording.
"""
import json
from datetime import date, timedelta

import pytest

from app.scorecards import upsert_scorecard
from tests.test_decision_flow_stabilization import modules, seed_thread


def _seed(db, user, tid, cards):
    seed_thread(user, tid, cards)
    for card in cards:
        upsert_scorecard(user_id=user.id, thread_id=tid, payload=card)
    db.session.commit()


def _cards():
    return [
        {'id': 'card-a', 'option_key': 'option-a', 'project_name': 'Adams County Bid',
         'jaspen_score': 72, 'score_category': 'Strong',
         'recommendation': {'verdict_key': 'advance', 'label': 'Bid'}},
        {'id': 'card-b', 'option_key': 'option-b', 'project_name': 'Boulder Transit Bid',
         'jaspen_score': 64, 'score_category': 'Promising',
         'recommendation': {'verdict_key': 'advance', 'label': 'Bid'}},
        {'id': 'card-c', 'option_key': 'option-c', 'project_name': 'Cherry Creek Bid',
         'jaspen_score': 41, 'score_category': 'Weak',
         'recommendation': {'verdict_key': 'advance', 'label': 'Bid'}},
    ]


def _call(agent, user, tid, tool, tool_input, message):
    return agent._execute_mutation_tool(
        tool, tool_input, user=user, user_id=user.id, thread_id=tid, user_message=message,
    )


def _set_history(user, tid, history):
    from app.routes.sessions import load_user_sessions, save_user_sessions
    sessions = load_user_sessions(user.id)
    sessions[tid]['chat_history'] = history
    assert save_user_sessions(user.id, sessions)


def _store_plan(user, tid, scorecard_id, tasks):
    strategy, _ = modules()
    stored = strategy._load_scenarios(user.id)
    entry = stored.get(tid) if isinstance(stored.get(tid), dict) else strategy._thread_entry()
    plan = {'name': 'Plan', 'scorecard_id': scorecard_id, 'created_at': '2026-10-20T10:00:00', 'tasks': tasks}
    entry.setdefault('wbs_by_scorecard', {})[scorecard_id] = plan
    entry['project_wbs'] = plan
    entry['active_execution_scorecard_id'] = scorecard_id
    stored[tid] = entry
    assert strategy._save_project_scenarios(user.id, stored, tid)


def _plan(user, tid, scorecard_id):
    strategy, _ = modules()
    return strategy._load_scenarios(user.id)[tid]['wbs_by_scorecard'][scorecard_id]


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _assert_no_customer_wording(result):
    """Tool results carry facts; never a question or a script for the AI."""
    for text in _strings({k: v for k, v in result.items() if k not in {'artifact', 'option_decisions', 'option_decision'}}):
        assert '?' not in text, text
        assert 'ask the user' not in text.casefold(), text
        assert 'in your own words' not in text.casefold(), text


def test_two_options_pursued_in_one_message_never_touch_the_sibling(app, db, test_user):
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'capture-two-pursued'
    _seed(db, test_user, tid, _cards())
    message = "We're bidding on Adams and Boulder, because both fit our crew."
    result = _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_name': 'Adams', 'disposition': 'pursue', 'user_request_quote': 'bidding on Adams',
         'rationale_quote': 'because both fit our crew'},
        {'option_name': 'Boulder', 'disposition': 'pursue', 'user_request_quote': 'Boulder'},
    ]}, message)

    assert result['ok'] is True, result
    assert [item['status'] for item in result['decisions']] == ['recorded', 'recorded']
    rows = OptionDecision.query.order_by(OptionDecision.option_key).all()
    assert [(row.option_key, row.disposition, row.source) for row in rows] == [
        ('option-a', 'pursue', 'conversation'), ('option-b', 'pursue', 'conversation'),
    ]
    assert OptionDecision.query.filter_by(option_key='option-c').count() == 0
    assert 'receipts' not in result and 'confirmation' not in result
    assert result['decisions'][0]['rationale_signal_id']
    _assert_no_customer_wording(result)


def test_still_evaluating_is_recorded_and_shown_in_facts(app, db, test_user):
    from app.decision_capture import decision_facts

    _, agent = modules()
    tid = 'capture-still-evaluating'
    _seed(db, test_user, tid, _cards())
    message = "Cherry Creek is still on the table, we haven't decided."
    result = _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-c', 'disposition': 'still_evaluating', 'user_request_quote': 'still on the table'},
    ]}, message)
    assert result['ok'] is True
    assert 'receipts' not in result and 'confirmation' not in result

    facts = decision_facts(test_user, tid)
    by_key = {item['option_key']: item for item in facts['options']}
    assert by_key['option-c']['disposition']['still_evaluating'] is True
    assert by_key['option-c']['disposition']['state'] == 'open'
    assert by_key['option-c']['disposition']['quote'] == 'still on the table'
    assert by_key['option-a']['disposition']['source'] == 'no_disposition'
    assert facts['reconciliation']['reconciles'] is True

    suffix = agent._decision_facts_prompt_suffix(test_user.id, tid)
    assert suffix.startswith('\n\n[DECISION STATE')
    assert '"still_evaluating":true' in suffix


def test_choice_card_answer_with_exclusive_option_records_choice_source(app, db, test_user):
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'capture-choice'
    _seed(db, test_user, tid, _cards())
    block = json.dumps({
        'question': 'Which bids are you pursuing?',
        'options': [
            {'label': 'Adams County Bid'}, {'label': 'Boulder Transit Bid'}, {'label': 'Cherry Creek Bid'},
            {'label': 'None of them', 'exclusive': True}, {'label': 'Still evaluating', 'exclusive': True},
        ],
        'allow_multi': True, 'allow_text': True,
    })
    answer = 'Adams County Bid, Cherry Creek Bid'
    _set_history(test_user, tid, [
        {'role': 'assistant', 'content': f'Where did you land?\n[[choice]]\n{block}\n[[/choice]]'},
        {'role': 'user', 'content': answer},
    ])
    assert agent.verify_user_quote('Cherry Creek Bid', answer)
    result = _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-a', 'disposition': 'pursue', 'user_request_quote': 'Adams County Bid'},
        {'option_key': 'option-c', 'disposition': 'pursue', 'user_request_quote': 'Cherry Creek Bid'},
    ]}, answer)

    assert result['ok'] is True
    rows = {row.option_key: row for row in OptionDecision.query.all()}
    assert {row.source for row in rows.values()} == {'choice'}
    assert rows['option-a'].capture_metadata['choice']['selected'] == ['Adams County Bid', 'Cherry Creek Bid']
    assert rows['option-a'].capture_metadata['choice']['exclusive_selected'] == []

    exclusive = 'Still evaluating'
    _set_history(test_user, tid, [
        {'role': 'assistant', 'content': f'[[choice]]\n{block}\n[[/choice]]'},
        {'role': 'user', 'content': exclusive},
    ])
    result = _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-b', 'disposition': 'still_evaluating', 'user_request_quote': exclusive},
    ]}, exclusive)
    row = OptionDecision.query.filter_by(option_key='option-b').one()
    assert row.source == 'choice'
    assert row.capture_metadata['choice']['exclusive_selected'] == ['Still evaluating']


def test_choice_answer_detection_is_exact_and_handles_commas_in_labels():
    from app.decision_capture import choice_answer_context

    block = json.dumps({'question': 'Q', 'allow_multi': True, 'options': [
        {'label': 'Build, then sell'}, {'label': 'Partner'}, {'label': 'None', 'exclusive': True},
    ]})
    history = [{'role': 'assistant', 'content': f'[[choice]]{block}[[/choice]]'}]
    assert choice_answer_context(history, 'Build, then sell, Partner')['selected'] == ['Build, then sell', 'Partner']
    assert choice_answer_context(history, 'Build, then sell')['selected'] == ['Build, then sell']
    assert choice_answer_context(history, 'Partner, maybe') is None
    assert choice_answer_context(history, 'I think we partner') is None
    assert choice_answer_context([{'role': 'assistant', 'content': 'no card'}], 'Partner') is None


def test_quote_mismatch_writes_nothing(app, db, test_user):
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'capture-quote-mismatch'
    _seed(db, test_user, tid, _cards())
    result = _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-a', 'disposition': 'pursue', 'user_request_quote': 'We bid on Adams'},
        {'option_key': 'option-b', 'disposition': 'not_pursue', 'user_request_quote': 'we pass on Boulder'},
    ]}, 'We bid on Adams. What do you think about Boulder?')
    assert result['ok'] is False
    assert result['code'] == 'decision_quote_required'
    assert OptionDecision.query.count() == 0


def test_pursuit_against_no_bid_is_recorded_with_the_recommendation_kept(app, db, test_user):
    from app.decision_capture import decision_facts
    from app.decision_records import create_or_refresh_record, option_dispositions
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'capture-override'
    cards = _cards()
    cards[2]['recommendation'] = {'verdict_key': 'decline', 'label': 'No-Bid'}
    _seed(db, test_user, tid, cards)
    message = "We're bidding on Cherry Creek and Adams anyway, the client relationship matters."
    _set_history(test_user, tid, [{'role': 'user', 'content': message}])
    result = _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-c', 'disposition': 'pursue', 'user_request_quote': 'bidding on Cherry Creek',
         'rationale_quote': 'the client relationship matters'},
        {'option_key': 'option-a', 'disposition': 'pursue', 'user_request_quote': 'Adams anyway'},
    ]}, message)

    assert result['ok'] is True, result
    assert 'confirmation_required' not in result and 'artifact' not in result
    assert 'receipts' not in result and 'pending_option_decisions' not in result
    statuses = {item['option_key']: item['status'] for item in result['decisions']}
    assert statuses == {'option-c': 'recorded', 'option-a': 'recorded'}
    against = next(item for item in result['decisions'] if item['option_key'] == 'option-c')['against_recommendation']
    assert against == {'override_of': 'decline', 'recommendation': 'No-Bid', 'failed_check_labels': []}
    assert 'against_recommendation' not in next(
        item for item in result['decisions'] if item['option_key'] == 'option-a'
    )
    _assert_no_customer_wording(result)

    row = OptionDecision.query.filter_by(option_key='option-c').one()
    assert (row.disposition, row.user_quote, row.rationale) == (
        'pursue', 'bidding on Cherry Creek', 'the client relationship matters',
    )
    assert row.override_info == {
        'override_of': 'decline', 'override_reason': 'the client relationship matters', 'failed_check_labels': [],
    }
    assert row.capture_metadata['against_recommendation'] is True

    facts = {item['option_key']: item for item in decision_facts(test_user, tid)['options']}
    assert facts['option-c']['disposition']['state'] == 'pursued'
    assert facts['option-c']['disposition']['against_recommendation']['override_of'] == 'decline'
    assert 'against_recommendation' not in facts['option-a']['disposition']
    record, _ = create_or_refresh_record(test_user, tid)
    derived = {item['option_key']: item for item in option_dispositions(record)['options']}
    assert derived['option-c']['against_recommendation'] is True
    assert derived['option-a']['against_recommendation'] is False
    assert derived['option-c']['state'] == 'pursued'


def test_legacy_single_form_still_maps_to_dispositions(app, db, test_user):
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'capture-legacy-single'
    _seed(db, test_user, tid, _cards())
    result = _call(agent, test_user, tid, 'record_option_decision', {
        'option_key': 'option-b', 'decision': 'deferred', 'user_request_quote': 'Park Boulder for now',
    }, 'Park Boulder for now.')
    assert result['ok'] is True
    row = OptionDecision.query.one()
    assert (row.disposition, row.final_decision, row.capture_metadata) == (
        'still_evaluating', 'Deferred Boulder Transit Bid.', {'deferred': True},
    )
    assert 'confirmation' not in result and 'receipts' not in result


def test_context_signals_commitment_review_and_retraction(app, db, test_user, monkeypatch):
    from app.decision_capture import decision_facts
    from app.models_decision_record import DecisionSignal

    _, agent = modules()
    sync_calls = []
    monkeypatch.setattr(
        agent, '_trigger_post_mutation_sync',
        lambda user_id, thread_id, plan: sync_calls.append((user_id, thread_id, plan)) or {'status': 'synced'},
    )
    tid = 'capture-context'
    _seed(db, test_user, tid, _cards())
    _store_plan(test_user, tid, 'card-a', [
        {'id': 't1', 'title': 'Submit bond', 'status': 'todo', 'due_date': '2026-11-18'},
        {'id': 't2', 'title': 'Site visit', 'status': 'todo', 'due_date': '2026-11-10'},
    ])

    message = 'The bond has to be submitted by November 20, that is our hard commitment.'
    result = _call(agent, test_user, tid, 'record_decision_context', {
        'kind': 'commitment', 'option_key': 'option-a', 'content': 'Bond submitted by Nov 20',
        'user_request_quote': 'submitted by November 20', 'structured': {'date': '2026-11-20'}, 'task_id': 't1',
    }, message)
    assert result['ok'] is True, result
    assert result['task_commitment']['status'] == 'recorded'
    assert result['task_commitment']['task_due_date_differs'] is False
    task = next(item for item in _plan(test_user, tid, 'card-a')['tasks'] if item['id'] == 't1')
    assert task['commitment']['basis'] == 'user_stated'
    assert task['commitment']['due_date'] == '2026-11-20'
    assert task['commitment']['ref'] == result['signal_id']
    assert task['due_date'] == '2026-11-20'
    assert task['history'][-1]['source'] == 'person'
    assert task['history'][-1]['field'] == 'due_date'
    assert task['history'][-1]['from'] == '2026-11-18'
    assert task['history'][-1]['to'] == '2026-11-20'
    assert result['task_commitment']['sync_status'] == {'status': 'synced'}
    assert sync_calls[0][2]['tasks'][0]['due_date'] == '2026-11-20'
    _assert_no_customer_wording(result)

    past = (date.today() - timedelta(days=3)).isoformat()
    measure = _call(agent, test_user, tid, 'record_decision_context', {
        'kind': 'success_measure', 'option_key': 'option-a', 'content': 'Win the award',
        'user_request_quote': 'success means winning the award', 'structured': {'review_by': past},
    }, 'For us success means winning the award.')
    assert measure['ok'] is True
    facts = decision_facts(test_user, tid)
    assert {'kind': 'review_due', 'option_key': 'option-a', 'review_by': past} in facts['follow_up_facts']
    option_a = next(item for item in facts['options'] if item['option_key'] == 'option-a')
    assert option_a['signals']['commitment']['count'] == 1
    assert option_a['success_measures'][0]['review_by'] == past

    bad = _call(agent, test_user, tid, 'record_decision_context', {
        'kind': 'assumption', 'content': 'Crew free', 'user_request_quote': 'crew is free',
        'structured': {'date': 'next week'},
    }, 'The crew is free next week.')
    assert bad['code'] == 'invalid_context_date'

    retract = _call(agent, test_user, tid, 'record_decision_context', {
        'kind': 'success_measure', 'option_key': 'option-a', 'retract_signal_id': measure['signal_id'],
        'user_request_quote': 'forget the award measure',
    }, 'Actually forget the award measure.')
    assert retract['ok'] is True and retract['retracted_signal_id'] == measure['signal_id']
    assert DecisionSignal.query.get(measure['signal_id']).retracted_at is not None
    facts = decision_facts(test_user, tid)
    assert not [item for item in facts['follow_up_facts'] if item['kind'] == 'review_due']


def test_context_signal_requires_a_verified_quote(app, db, test_user):
    from app.models_decision_record import DecisionSignal

    _, agent = modules()
    tid = 'capture-context-quote'
    _seed(db, test_user, tid, _cards())
    result = _call(agent, test_user, tid, 'record_decision_context', {
        'kind': 'concern', 'content': 'Labor shortage', 'user_request_quote': 'labor is short',
    }, 'Tell me more about the risks.')
    assert result['code'] == 'decision_quote_required'
    assert DecisionSignal.query.count() == 0


def test_confirm_task_commitment_writes_person_confirmed(app, db, test_user):
    _, agent = modules()
    tid = 'capture-confirm-task'
    _seed(db, test_user, tid, _cards())
    _store_plan(test_user, tid, 'card-b', [
        {'id': 't9', 'title': 'Kickoff', 'status': 'todo', 'due_date': '2026-12-01'},
    ])
    result = _call(agent, test_user, tid, 'confirm_task_commitment', {
        'task_id': 't9', 'option_key': 'option-b', 'user_request_quote': 'December 1 works',
    }, 'Yes, December 1 works for kickoff.')
    assert result['ok'] is True, result
    task = _plan(test_user, tid, 'card-b')['tasks'][0]
    assert task['commitment']['basis'] == 'person_confirmed'
    assert task['commitment']['due_date'] == '2026-12-01'
    assert 'receipts' not in result and 'confirmation' not in result

    again = _call(agent, test_user, tid, 'confirm_task_commitment', {
        'task_id': 't9', 'option_key': 'option-b', 'user_request_quote': 'still December 1',
    }, 'still December 1')
    assert again['already_committed'] is True and 'receipts' not in again
    _assert_no_customer_wording(again)


def test_outcome_too_early_then_achieved_objective_met_needs_quote_and_lesson_links(app, db, test_user):
    from app.decision_capture import decision_facts
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'capture-outcomes'
    _seed(db, test_user, tid, _cards())
    _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-a', 'disposition': 'pursue', 'user_request_quote': 'go with Adams'},
    ]}, "Let's go with Adams.")

    early = _call(agent, test_user, tid, 'record_outcome', {
        'option_key': 'option-a', 'status': 'too_early', 'summary': 'Award not announced',
        'user_request_quote': "haven't heard yet",
    }, "We haven't heard yet on Adams.")
    assert early['ok'] is True
    assert decision_facts(test_user, tid)['options'][0]['outcome_state'] == 'awaiting_measurement'

    no_quote = _call(agent, test_user, tid, 'record_outcome', {
        'option_key': 'option-a', 'status': 'achieved', 'summary': 'Won the award',
        'objective_met': True, 'objective_met_quote': 'it met our goal',
        'user_request_quote': 'we won Adams',
    }, 'Great news, we won Adams.')
    assert no_quote['ok'] is True
    assert no_quote['objective_met_stored'] is False and no_quote['objective_met_dropped'] is True

    met = _call(agent, test_user, tid, 'record_outcome', {
        'option_key': 'option-a', 'status': 'achieved', 'summary': 'Won and met margin goal',
        'objective_met': True, 'objective_met_quote': 'hit our margin goal',
        'user_request_quote': 'We won', 'metrics': [{'label': 'Margin', 'value': '14', 'expected': '12', 'unit': '%'}],
    }, 'We won, and we hit our margin goal.')
    row = OptionDecision.query.filter_by(option_key='option-a', superseded_at=None).one()
    statuses = [(item['status'], item['objective_met'], item['source']) for item in row.outcomes]
    assert statuses == [('too_early', None, 'conversation'), ('achieved', None, 'conversation'), ('achieved', True, 'conversation')]
    assert row.outcomes[2]['objective_met_quote'] == 'hit our margin goal'
    assert 'receipts' not in met and 'confirmation' not in met

    lesson = _call(agent, test_user, tid, 'record_lesson', {
        'option_key': 'option-a', 'lesson': 'Early bonding wins time', 'outcome_id': met['outcome_id'],
        'user_request_quote': 'lining up the bond early',
    }, 'The lesson is lining up the bond early saved us.')
    assert lesson['ok'] is True
    db.session.refresh(row)
    assert row.lessons_learned[0]['outcome_id'] == met['outcome_id']
    assert row.lessons_learned[0]['user_quote'] == 'lining up the bond early'
    facts = decision_facts(test_user, tid)
    assert facts['options'][0]['outcome_state'] == 'measured'
    assert facts['options'][0]['lessons_count'] == 1


def test_outcome_on_an_undecided_option_returns_a_fact(app, db, test_user):
    _, agent = modules()
    tid = 'capture-outcome-undecided'
    _seed(db, test_user, tid, _cards())
    result = _call(agent, test_user, tid, 'record_outcome', {
        'option_key': 'option-b', 'status': 'achieved', 'summary': 'Won', 'user_request_quote': 'we won Boulder',
    }, 'we won Boulder')
    assert result['ok'] is False and result['code'] == 'option_decision_required'


def test_facts_never_leak_between_sessions(app, db, test_user):
    from app.decision_capture import decision_facts

    _, agent = modules()
    _seed(db, test_user, 'capture-iso-a', _cards())
    other = [{'id': 'other-card', 'option_key': 'option-other', 'project_name': 'Secret Option', 'jaspen_score': 50}]
    _seed(db, test_user, 'capture-iso-b', other)
    _call(agent, test_user, 'capture-iso-b', 'record_option_decision', {'decisions': [
        {'option_key': 'option-other', 'disposition': 'pursue', 'user_request_quote': 'Secret Option it is'},
    ]}, 'Secret Option it is.')
    _call(agent, test_user, 'capture-iso-a', 'record_option_decision', {'decisions': [
        {'option_key': 'option-a', 'disposition': 'pursue', 'user_request_quote': 'Adams'},
    ]}, 'Adams.')
    facts_a = json.dumps(decision_facts(test_user, 'capture-iso-a'))
    assert 'Secret Option' not in facts_a and 'option-other' not in facts_a
    assert 'Secret Option' not in agent._decision_facts_prompt_suffix(test_user.id, 'capture-iso-a')


def test_plan_conflict_and_complete_without_outcome_are_follow_up_facts(app, db, test_user):
    from app.decision_capture import decision_facts

    _, agent = modules()
    tid = 'capture-follow-up'
    _seed(db, test_user, tid, _cards())
    _store_plan(test_user, tid, 'card-a', [{'id': 't1', 'title': 'Done task', 'status': 'done'}])
    _store_plan(test_user, tid, 'card-b', [{'id': 't2', 'title': 'Open task', 'status': 'todo'}])
    _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-b', 'disposition': 'not_pursue', 'user_request_quote': 'drop Boulder'},
    ]}, "Let's drop Boulder.")
    kinds = {(item['kind'], item['option_key']) for item in decision_facts(test_user, tid)['follow_up_facts']}
    assert ('implementation_complete_without_outcome', 'option-a') in kinds
    # Dropping an option that has a plan is the customer's decision, not a conflict.
    assert ('plan_conflicts_disposition', 'option-b') not in kinds

    from app.decision_capture import find_thread_record
    from app.decision_records import record_option_decision
    record = find_thread_record(test_user, tid)
    record_option_decision(
        record, 'option-b', 'Moving forward with Boulder Transit Bid.', source='plan_created',
        disposition='pursue', option_name='Boulder Transit Bid',
    )
    conflicts = [
        item for item in decision_facts(test_user, tid)['follow_up_facts']
        if item['kind'] == 'plan_conflicts_disposition'
    ]
    assert conflicts and conflicts[0]['option_key'] == 'option-b'
    assert conflicts[0]['stated_disposition'] == 'not_pursue'


def test_capture_writes_are_exempt_from_the_content_mutation_cap(app):
    _, agent = modules()
    for tool in ('record_option_decision', 'record_decision_context', 'confirm_task_commitment',
                 'record_outcome', 'record_lesson'):
        assert agent._is_mutation_tool(tool)
        assert agent._guard_mutation_tool(
            tool, user_turn_count=1, mutations_this_turn=99, user_message='x',
        ) is None


def test_capture_code_paths_contain_no_canned_customer_sentences():
    """Guard: the capture paths and prompt guidance never script the AI."""
    import inspect

    _, agent = modules()
    from app import decision_capture

    sources = [inspect.getsource(decision_capture)] + [
        inspect.getsource(getattr(agent, name)) for name in (
            '_execute_record_option_decision', '_execute_record_decision_context',
            '_execute_confirm_task_commitment', '_execute_record_outcome', '_execute_record_lesson',
            '_decision_facts_prompt_suffix', '_against_recommendation', '_normalize_decision_conditions',
        )
    ]
    combined = '\n'.join(sources)
    for banned in (
        "record it?", "which option did you mean", "That overrides Jaspen's No-Bid",
        "A confirmation card is shown; ask", "Would you like", "Do you want",
        "Decision recorded", "Recorded: ", "Commitment recorded", "Outcome recorded", "Lesson recorded",
    ):
        assert banned.casefold() not in combined.casefold(), banned
    guidance = agent._SYSTEM_PROMPT_PREFIX
    start = guidance.index('DECISION INTELLIGENCE')
    section = guidance[start:guidance.index('When the user asks to start the plan', start)]
    # Responsibilities only: no quoted lines to repeat and no scripted questions.
    assert '"' not in section
    assert '?' not in section


@pytest.mark.parametrize('message', ['We pass on Boulder.', 'Boulder, Adams County Bid'])
def test_verify_user_quote_accepts_quotes_from_the_sent_message(app, message):
    _, agent = modules()
    assert agent.verify_user_quote('Boulder', message)


def test_stale_pending_override_state_is_ignored_and_dropped(app, db, test_user):
    from app.models_decision_record import OptionDecision
    from app.routes.sessions import load_user_sessions, save_user_sessions

    _, agent = modules()
    tid = 'capture-override-stale'
    cards = _cards()
    cards[2]['recommendation'] = {'verdict_key': 'decline', 'label': 'No-Bid'}
    _seed(db, test_user, tid, cards)
    sessions = load_user_sessions(test_user.id)
    sessions[tid]['pending_option_decisions'] = {'option-c': {
        'option_key': 'option-c', 'disposition': 'pursue', 'user_request_quote': 'old quote',
        'override_of': 'decline', 'requested_user_turn': 1,
    }}
    assert save_user_sessions(test_user.id, sessions)

    message = 'Go with Cherry Creek.'
    session = load_user_sessions(test_user.id)[tid]
    result, _ = agent._execute_local_tool(
        'record_option_decision', {'decisions': [
            {'option_key': 'option-c', 'disposition': 'pursue', 'user_request_quote': 'Go with Cherry Creek'},
        ]},
        readiness={}, user=test_user, user_id=test_user.id, thread_id=tid,
        user_turn_count=2, mutations_this_turn=0, user_message=message, session=session,
    )
    assert result['ok'] is True and result['decisions'][0]['status'] == 'recorded'
    row = OptionDecision.query.filter_by(option_key='option-c').one()
    assert row.user_quote == 'Go with Cherry Creek'
    assert 'pending_option_decisions' not in session and 'pending_option_decision' not in session


def test_choice_provenance_survives_artifact_cards_after_the_reply():
    from app.decision_capture import choice_answer_context

    block = json.dumps({'question': 'Q', 'options': [{'label': 'Adams'}, {'label': 'Boulder'}]})
    history = [
        {'role': 'user', 'content': 'compare them'},
        {'role': 'assistant', 'content': f'Here is the comparison.[[choice]]{block}[[/choice]]'},
        {'role': 'assistant', 'content': '', 'artifact': {'type': 'receipts', 'data': {}}},
        {'role': 'assistant', 'content': '', 'artifact': {'type': 'comparison', 'data': {}}},
        {'role': 'user', 'content': 'Boulder'},
    ]
    assert choice_answer_context(history, 'Boulder')['selected'] == ['Boulder']
    older = [history[1], {'role': 'user', 'content': 'something else'}, {'role': 'user', 'content': 'Boulder'}]
    assert choice_answer_context(older, 'Boulder') is None


def test_record_decision_context_schema_accepts_task_id(app):
    _, agent = modules()
    tool = next(
        item for item in agent._anthropic_tool_definitions(enable_mutation_tools=True)
        if item['name'] == 'record_decision_context'
    )
    assert 'task_id' in tool['input_schema']['properties']


def test_failed_capture_withholds_prose_and_shows_truthful_status(app):
    _, agent = modules()
    action = {'tool': 'record_outcome', 'result': {
        'ok': False, 'code': 'option_decision_required', 'error': 'internal guidance',
    }}
    reply, failure = agent._apply_option_decision_failure_state('Recorded your outcome!', [action])
    assert reply == '' and failure['tool'] == 'record_outcome'
    card = agent._artifact_entries_from_actions([action], user_message='We won Boulder.')[0]['artifact']['data']
    assert card['message'] == 'Nothing saved yet: no decision is recorded for that option.'

    quote_fail = {'tool': 'record_lesson', 'result': {'ok': False, 'code': 'decision_quote_required', 'error': 'Quote the user'}}
    card = agent._artifact_entries_from_actions([quote_fail], user_message='lesson')[0]['artifact']['data']
    assert card['message'] == "This wasn't saved. Your message is saved."
    assert card['retry_message'] == 'lesson'

    ok_then_fail = [
        {'tool': 'record_lesson', 'result': {'ok': True, 'receipts': ['Lesson recorded.']}},
        quote_fail,
    ]
    assert agent._apply_option_decision_failure_state('Saved.', ok_then_fail) == ('Saved.', None)


def test_failed_plan_edits_withhold_prose_until_same_target_succeeds(app):
    _, agent = modules()
    failed_due_date = {
        'tool': 'update_wbs_task',
        'input': {'task_id': 'task-bond', 'field': 'due_date', 'new_value': '2026-11-24'},
        'result': {'ok': False, 'code': 'task_not_found', 'error': 'Task not found.'},
    }

    reply, failure = agent._apply_option_decision_failure_state(
        'Moving its due date to Nov 24.', [failed_due_date],
    )
    assert reply == ''
    assert failure['tool'] == 'update_wbs_task'
    card = agent._artifact_entries_from_actions(
        [failed_due_date], user_message='Move the bond deadline to Nov 24.',
    )[0]['artifact']['data']
    assert card == {
        'tone': 'error',
        'message': "The due date change for that task wasn't saved: the task wasn't found. Your message is saved.",
    }

    succeeded_due_date = {
        **failed_due_date,
        'result': {'ok': True, 'confirmation': "Updated task 'Bond letter' (due_date)."},
    }
    assert agent._apply_option_decision_failure_state(
        'Moved the deadline.', [failed_due_date, succeeded_due_date],
    ) == ('Moved the deadline.', None)

    unrelated_success = {
        'tool': 'update_wbs_task',
        'input': {'task_id': 'task-permit', 'field': 'owner', 'new_value': 'Priya'},
        'result': {'ok': True, 'confirmation': "Updated task 'Permit' (owner)."},
    }
    actions = [failed_due_date, unrelated_success]
    assert agent._apply_option_decision_failure_state('Both are updated.', actions)[0] == ''
    entries = agent._artifact_entries_from_actions(actions, user_message='Update both tasks.')
    receipts = next(item['artifact']['data'] for item in entries if item['artifact']['type'] == 'receipts')
    assert receipts['items'] == ["Updated task 'Permit' (owner)."]
    assert any(item['artifact']['type'] == 'status' for item in entries)


def test_plan_edit_failure_cards_distinguish_invalid_date_and_conflict(app):
    _, agent = modules()
    invalid = {'tool': 'update_wbs_task', 'input': {
        'task_id': 'task-bond', 'field': 'due_date', 'new_value': 'Nov 24',
    }, 'result': {'ok': False, 'code': 'invalid_task_date', 'error': 'invalid'}}
    conflict = {'tool': 'set_execution_start_date', 'input': {
        'start_date': '2026-11-24',
    }, 'result': {'ok': False, 'code': 'revision_conflict', 'error': 'conflict'}}

    invalid_card = agent._artifact_entries_from_actions(
        [invalid], user_message='Move the deadline.',
    )[0]['artifact']['data']
    assert "the date wasn't valid" in invalid_card['message']
    assert 'retry_message' not in invalid_card

    conflict_card = agent._artifact_entries_from_actions(
        [conflict], user_message='Move the plan start.',
    )[0]['artifact']['data']
    assert 'the plan changed before this update could be saved' in conflict_card['message']
    assert conflict_card['retry_message'] == 'Move the plan start.'


def test_partial_multi_option_call_states_what_was_not_saved(app, db, test_user):
    _, agent = modules()
    tid = 'capture-partial'
    cards = _cards() + [{'id': 'card-d', 'option_key': 'option-d', 'project_name': 'Adams Rail Bid'}]
    _seed(db, test_user, tid, cards)
    message = 'We are pursuing Boulder and Adams.'
    result = _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_name': 'Boulder', 'disposition': 'pursue', 'user_request_quote': 'Boulder'},
        {'option_name': 'Adams', 'disposition': 'pursue', 'user_request_quote': 'Adams'},
    ]}, message)
    assert [item['status'] for item in result['decisions']] == ['recorded', 'not_recorded']
    entries = agent._artifact_entries_from_actions(
        [{'tool': 'record_option_decision', 'result': result}], user_message=message,
    )
    types = [item['artifact']['type'] for item in entries]
    assert 'receipts' not in types
    status = next(item['artifact']['data'] for item in entries if item['artifact']['type'] == 'status')
    assert status['message'] == "Nothing saved yet for one option: it wasn't clear which."
    # The option-name buttons are back so the customer can answer in one click.
    assert [a['value'] for a in status['actions']] == ['Adams County Bid', 'Adams Rail Bid']


def test_capture_only_turns_offer_no_undo(app):
    _, agent = modules()
    assert not agent._has_undoable_mutations([{'tool': 'record_lesson', 'success': True}])
    assert not agent._has_undoable_mutations([{'tool': 'record_option_decision', 'success': True}])
    assert agent._has_undoable_mutations([{'tool': 'confirm_task_commitment', 'success': True}])
    assert agent._has_undoable_mutations([{'tool': 'update_wbs_task', 'success': True}])


# ── Phase 1 corrections (Nov 6 live test) ──────────────────────────────────


def _kit_cards():
    cards = _cards()
    cards[2]['recommendation'] = {'verdict_key': 'decline', 'label': 'No-Bid'}
    return cards


def _use_rfp_kit(user, tid):
    from app.routes.sessions import load_user_sessions, save_user_sessions
    sessions = load_user_sessions(user.id)
    sessions[tid]['decision_kit'] = 'rfp_bid'
    assert save_user_sessions(user.id, sessions)


def test_conditional_pursuit_counts_as_pursued_with_open_condition(app, db, test_user):
    from app.decision_capture import decision_facts
    from app.decision_records import create_or_refresh_record, option_dispositions
    from app.models_decision_record import DecisionSignal, OptionDecision

    _, agent = modules()
    tid = 'capture-conditional'
    _seed(db, test_user, tid, _kit_cards())
    _use_rfp_kit(test_user, tid)
    message = "We'll pursue Cherry Creek contingent on bonding, and Adams if the sub signs by Dec 1."
    result = _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-c', 'disposition': 'pursue', 'user_request_quote': 'pursue Cherry Creek',
         'conditions': [{'content': 'Acceptable bonding secured', 'user_quote': 'contingent on bonding'}]},
        {'option_key': 'option-a', 'disposition': 'pursue', 'user_request_quote': 'Adams',
         'conditions': [{'content': 'Subcontractor signs', 'user_quote': 'if the sub signs by Dec 1',
                         'due_by': '2026-12-01'}]},
    ]}, message)
    assert result['ok'] is True, result
    assert 'receipts' not in result and 'artifact' not in result
    _assert_no_customer_wording(result)

    rows = {row.option_key: row for row in OptionDecision.query.all()}
    assert rows['option-c'].disposition == 'pursue'
    assert rows['option-c'].kit_verdict['verdict_key'] == 'advance_with_conditions'
    assert rows['option-c'].capture_metadata['conditional'] is True
    assert rows['option-c'].capture_metadata['against_recommendation'] is True
    conditions = DecisionSignal.query.filter_by(kind='condition').order_by(DecisionSignal.option_key).all()
    assert [(c.option_key, c.structured.get('status'), c.user_quote) for c in conditions] == [
        ('option-a', 'open', 'if the sub signs by Dec 1'),
        ('option-c', 'open', 'contingent on bonding'),
    ]
    assert conditions[0].structured['due_by'] == '2026-12-01'

    facts = {item['option_key']: item for item in decision_facts(test_user, tid, today=date(2026, 12, 5))['options']}
    assert facts['option-c']['disposition']['state'] == 'pursued'
    assert facts['option-c']['disposition']['conditional'] is True
    assert facts['option-c']['conditions'][0]['status'] == 'open'
    follow = decision_facts(test_user, tid, today=date(2026, 12, 5))['follow_up_facts']
    assert {'kind': 'condition_past_due', 'option_key': 'option-a',
            'condition_signal_id': str(conditions[0].id), 'due_by': '2026-12-01'} in follow

    record, _ = create_or_refresh_record(test_user, tid)
    derived = option_dispositions(record)
    by_key = {item['option_key']: item for item in derived['options']}
    assert by_key['option-c']['state'] == 'pursued'
    assert by_key['option-c']['conditions'] == {'open': 1}
    # The five agreed metrics stay as they are.
    assert set(derived['reconciliation']) == {
        'pursued', 'not_pursued', 'open', 'archived', 'scored_options', 'reconciles',
    }
    assert derived['reconciliation']['pursued'] == 2 and derived['reconciliation']['reconciles'] is True


def test_condition_status_changes_keep_history_and_need_the_customer(app, db, test_user):
    from app.decision_capture import decision_facts
    from app.models_decision_record import DecisionSignal

    _, agent = modules()
    tid = 'capture-condition-status'
    _seed(db, test_user, tid, _kit_cards())
    first = 'Pursue Cherry Creek contingent on bonding.'
    _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-c', 'disposition': 'pursue', 'user_request_quote': 'Pursue Cherry Creek',
         'conditions': [{'content': 'Bonding secured', 'user_quote': 'contingent on bonding'}]},
    ]}, first)
    open_condition = DecisionSignal.query.filter_by(kind='condition').one()

    # A status change needs the current condition id and the customer's words.
    missing = _call(agent, test_user, tid, 'record_decision_context', {
        'kind': 'condition', 'option_key': 'option-c', 'content': 'Bonding secured',
        'structured': {'status': 'met'}, 'user_request_quote': 'bonding came through',
    }, 'Good news, bonding came through.')
    assert missing['ok'] is False and missing['code'] == 'condition_signal_required'
    unquoted = _call(agent, test_user, tid, 'record_decision_context', {
        'kind': 'condition', 'condition_signal_id': str(open_condition.id),
        'structured': {'status': 'met'}, 'user_request_quote': 'the surety approved it',
    }, 'Good news, bonding came through.')
    assert unquoted['ok'] is False and unquoted['code'] == 'decision_quote_required'

    met = _call(agent, test_user, tid, 'record_decision_context', {
        'kind': 'condition', 'condition_signal_id': str(open_condition.id),
        'structured': {'status': 'met'}, 'user_request_quote': 'bonding came through',
    }, 'Good news, bonding came through.')
    assert met['ok'] is True, met
    assert met['superseded_condition_id'] == str(open_condition.id)
    assert 'receipts' not in met

    rows = DecisionSignal.query.filter_by(kind='condition').order_by(DecisionSignal.created_at).all()
    assert [(row.structured['status'], row.retracted_at) for row in rows] == [('open', None), ('met', None)]
    assert rows[1].supersedes_id == str(open_condition.id) and rows[1].option_key == 'option-c'
    facts = {item['option_key']: item for item in decision_facts(test_user, tid)['options']}
    current = facts['option-c']['conditions']
    assert len(current) == 1 and current[0]['status'] == 'met' and current[0]['earlier_statuses'] == 1

    again = _call(agent, test_user, tid, 'record_decision_context', {
        'kind': 'condition', 'condition_signal_id': str(open_condition.id),
        'structured': {'status': 'waived'}, 'user_request_quote': 'waived',
    }, 'They waived it.')
    assert again['ok'] is False and again['code'] == 'condition_superseded'


def test_conditions_belong_to_pursuits_and_need_quotes(app, db, test_user):
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'capture-condition-validation'
    _seed(db, test_user, tid, _cards())
    message = 'Not Boulder unless the price drops.'
    wrong_disposition = _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-b', 'disposition': 'not_pursue', 'user_request_quote': 'Not Boulder',
         'conditions': [{'content': 'Price drops', 'user_quote': 'unless the price drops'}]},
    ]}, message)
    assert wrong_disposition['ok'] is False and wrong_disposition['code'] == 'invalid_decision_conditions'
    unquoted = _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-b', 'disposition': 'pursue', 'user_request_quote': 'Boulder',
         'conditions': [{'content': 'Price drops', 'user_quote': 'if pricing falls'}]},
    ]}, message)
    assert unquoted['ok'] is False and unquoted['code'] == 'decision_condition_quote_required'
    assert OptionDecision.query.count() == 0


def test_deadline_and_commitment_are_kept_distinct(app, db, test_user):
    from app.decision_capture import decision_facts
    from app.models_decision_record import DecisionSignal

    _, agent = modules()
    tid = 'capture-deadline'
    _seed(db, test_user, tid, _cards())
    message = "Bid is due Dec 12, and we'll have the surety letter for Adams by Friday Dec 5."
    deadline = _call(agent, test_user, tid, 'record_decision_context', {
        'kind': 'deadline', 'content': 'Bid due', 'structured': {'date': '2026-12-12', 'set_by': 'client'},
        'user_request_quote': 'Bid is due Dec 12',
    }, message)
    commitment = _call(agent, test_user, tid, 'record_decision_context', {
        'kind': 'commitment', 'option_key': 'option-a', 'content': 'Surety letter ready',
        'structured': {'date': '2026-12-05', 'owner': 'our team'},
        'user_request_quote': "we'll have the surety letter for Adams by Friday Dec 5",
    }, message)
    no_date = _call(agent, test_user, tid, 'record_decision_context', {
        'kind': 'deadline', 'content': 'Bid due', 'user_request_quote': 'Bid is due',
    }, message)
    assert deadline['ok'] is True and commitment['ok'] is True
    assert no_date['ok'] is False and no_date['code'] == 'invalid_context_date'
    assert 'receipts' not in deadline and 'receipts' not in commitment

    rows = {row.kind: row for row in DecisionSignal.query.all()}
    assert (rows['deadline'].option_key, rows['deadline'].structured) == (
        None, {'date': '2026-12-12', 'set_by': 'client'},
    )
    assert (rows['commitment'].option_key, rows['commitment'].structured) == (
        'option-a', {'date': '2026-12-05', 'owner': 'our team'},
    )
    facts = decision_facts(test_user, tid)
    assert facts['decision_level']['deadlines'] == [{
        'signal_id': str(rows['deadline'].id), 'content': 'Bid due', 'date': '2026-12-12', 'set_by': 'client',
    }]
    by_key = {item['option_key']: item for item in facts['options']}
    assert by_key['option-a']['deadlines'] == []
    assert by_key['option-a']['signals']['commitment']['count'] == 1


def test_background_note_failure_never_replaces_the_reply(app):
    _, agent = modules()
    failed_note = {'tool': 'record_decision_context', 'result': {
        'ok': False, 'code': 'decision_quote_required', 'error': 'Quote the user',
    }}
    assert agent._apply_option_decision_failure_state('Here is the comparison.', [failed_note]) == (
        'Here is the comparison.', None,
    )
    assert agent._artifact_entries_from_actions([failed_note], user_message='Bid is due Dec 12.') == []
    # A failed decision save still withholds prose that may claim it saved.
    failed_decision = {'tool': 'record_option_decision', 'result': {
        'ok': False, 'code': 'decision_quote_required', 'error': 'Quote the user',
    }}
    assert agent._apply_option_decision_failure_state('Recorded!', [failed_decision])[0] == ''


def test_capture_results_never_produce_receipts_even_if_present(app):
    _, agent = modules()
    actions = [{'tool': tool, 'result': {'ok': True, 'receipts': ['Saved.'], 'confirmation': 'Saved.'}}
               for tool in agent._DECISION_CAPTURE_TOOLS]
    assert agent._artifact_entries_from_actions(actions, user_message='x') == []


def test_tool_trace_carries_names_and_codes_only(app):
    _, agent = modules()
    result = {'ok': True, 'decisions': [
        {'status': 'recorded', 'disposition': 'pursue', 'option_name': 'Secret Bid', 'option_key': 'k'},
    ], 'kind': 'deadline', 'content': 'customer words', 'user_quote': 'customer words'}
    entry = agent._tool_trace_entry('record_option_decision', result, thread_id='t1', user_turn_count=3)
    assert entry == {
        'event': 'agent_tool_call', 'thread_id': 't1', 'user_turn': 3, 'tool': 'record_option_decision',
        'ok': True, 'code': None, 'kind': 'deadline',
        'decision_statuses': [{'status': 'recorded', 'disposition': 'pursue', 'code': None}],
    }
    assert 'customer words' not in json.dumps(entry) and 'Secret Bid' not in json.dumps(entry)


def _fake_plan_build(strategy, agent, monkeypatch):
    calls = []
    monkeypatch.setattr(strategy, 'get_llm_client', lambda: object())

    def fake_plan(*args, **kwargs):
        calls.append(kwargs)
        required = [item for item in kwargs.get('lineage_sources', []) if item.get('required')]
        return ({'tasks': [{
            'id': 'task-1', 'title': 'Kickoff', 'estimated_days': 2,
            'lineage': [{'type': item['type'], 'ref': item['ref']} for item in required],
        }]}, {'provider': 'test', 'input_tokens': 1, 'output_tokens': 1}, True, None)

    monkeypatch.setattr(strategy, '_generate_ai_wbs_suggestion', fake_plan)

    def fake_operation(_user, *, generate, **kwargs):
        generated, usage = generate()
        return generated, usage, {'charged_credits': 0, 'reserved_credits': 0}

    monkeypatch.setattr(agent, 'execute_customer_operation', fake_operation)
    return calls


def test_exploratory_plan_records_no_decision_and_is_not_pursued(app, db, test_user, monkeypatch):
    from app.decision_records import create_or_refresh_record, option_dispositions
    from app.models_decision_record import OptionDecision

    strategy, agent = modules()
    tid = 'capture-exploratory-plan'
    _seed(db, test_user, tid, _cards())
    _fake_plan_build(strategy, agent, monkeypatch)
    built = agent._execute_mutation_tool(
        'generate_execution_plan', {'scorecard_id': 'card-b', 'planning_intent': 'exploratory'},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert built['ok'] is True, built
    assert built.get('confirmation_required') is not True
    assert built['decision_recorded'] is False and built['planning_intent'] == 'exploratory'
    assert OptionDecision.query.count() == 0
    record, _ = create_or_refresh_record(test_user, tid)
    by_key = {item['option_key']: item for item in option_dispositions(record)['options']}
    assert by_key['option-b']['state'] == 'open'
    assert by_key['option-b']['state_source'] == 'exploratory_plan'
    assert by_key['option-b']['plan_ids'] == ['card-b']


def test_missing_planning_intent_records_nothing(app, db, test_user, monkeypatch):
    from app.models_decision_record import OptionDecision

    strategy, agent = modules()
    tid = 'capture-unstated-plan'
    _seed(db, test_user, tid, _cards())
    _fake_plan_build(strategy, agent, monkeypatch)
    built = agent._execute_mutation_tool(
        'generate_execution_plan', {'scorecard_id': 'card-a'},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert built['ok'] is True and built['decision_recorded'] is False
    assert OptionDecision.query.count() == 0


def test_committed_plan_keeps_the_customers_own_pursue_row(app, db, test_user, monkeypatch):
    from app.models_decision_record import OptionDecision

    strategy, agent = modules()
    tid = 'capture-plan-keeps-row'
    _seed(db, test_user, tid, _kit_cards())
    message = 'Pursue Cherry Creek contingent on bonding.'
    _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-c', 'disposition': 'pursue', 'user_request_quote': 'Pursue Cherry Creek',
         'conditions': [{'content': 'Bonding secured', 'user_quote': 'contingent on bonding'}]},
    ]}, message)
    _fake_plan_build(strategy, agent, monkeypatch)
    built = agent._execute_mutation_tool(
        'generate_execution_plan', {'scorecard_id': 'card-c', 'planning_intent': 'committed'},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert built['ok'] is True, built
    rows = OptionDecision.query.filter_by(option_key='option-c').all()
    assert len(rows) == 1
    assert (rows[0].source, rows[0].user_quote, rows[0].superseded_at) == (
        'conversation', 'Pursue Cherry Creek', None,
    )


def test_committed_plan_after_not_pursue_keeps_history_and_flags_it(app, db, test_user, monkeypatch):
    from app.decision_capture import decision_facts
    from app.models_decision_record import OptionDecision

    strategy, agent = modules()
    tid = 'capture-plan-after-no'
    _seed(db, test_user, tid, _cards())
    _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-b', 'disposition': 'not_pursue', 'user_request_quote': 'pass on Boulder'},
    ]}, 'We pass on Boulder.')
    _fake_plan_build(strategy, agent, monkeypatch)
    built = agent._execute_mutation_tool(
        'generate_execution_plan', {'scorecard_id': 'card-b', 'planning_intent': 'committed'},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert built['ok'] is True and built['decision_recorded'] is True
    rows = OptionDecision.query.filter_by(option_key='option-b').order_by(OptionDecision.created_at).all()
    assert [(row.disposition, row.superseded_at is None) for row in rows] == [
        ('not_pursue', False), ('pursue', True),
    ]
    follow = decision_facts(test_user, tid)['follow_up_facts']
    assert any(item['kind'] == 'plan_conflicts_disposition' and item['option_key'] == 'option-b' for item in follow)


def test_plan_tool_schema_states_intent_and_guidance_has_no_fixed_confirmation(app):
    _, agent = modules()
    tool = next(
        item for item in agent._anthropic_tool_definitions(enable_mutation_tools=True)
        if item['name'] == 'generate_execution_plan'
    )
    assert tool['input_schema']['properties']['planning_intent']['enum'] == ['committed', 'exploratory']
    context = next(
        item for item in agent._anthropic_tool_definitions(enable_mutation_tools=True)
        if item['name'] == 'record_decision_context'
    )
    kinds = context['input_schema']['properties']['kind']['enum']
    assert 'deadline' in kinds and 'condition' in kinds
    decision = next(
        item for item in agent._anthropic_tool_definitions(enable_mutation_tools=True)
        if item['name'] == 'record_option_decision'
    )
    assert 'conditions' in decision['input_schema']['properties']['decisions']['items']['properties']
    guidance = agent._SYSTEM_PROMPT_PREFIX
    assert 'decision_acknowledged' not in guidance
    assert "this records that you're moving forward" not in guidance.casefold()
    assert 'confirmation card is shown; ask once' not in guidance


# ── Review fixes ───────────────────────────────────────────────────────────


def test_exploratory_plan_stays_exploratory_after_an_edit(app, db, test_user, monkeypatch):
    from app.decision_records import create_or_refresh_record, option_dispositions

    strategy, agent = modules()
    tid = 'capture-exploratory-edit'
    _seed(db, test_user, tid, _cards())
    _fake_plan_build(strategy, agent, monkeypatch)
    built = agent._execute_mutation_tool(
        'generate_execution_plan', {'scorecard_id': 'card-b', 'planning_intent': 'exploratory'},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert built['ok'] is True, built
    task_id = built['project_wbs']['tasks'][0]['id']
    edited = agent._execute_mutation_tool(
        'update_wbs_task', {'task_id': task_id, 'field': 'status', 'new_value': 'in_progress'},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert edited['ok'] is True, edited
    assert _plan(test_user, tid, 'card-b')['planning_intent'] == 'exploratory'
    record, _ = create_or_refresh_record(test_user, tid)
    by_key = {item['option_key']: item for item in option_dispositions(record)['options']}
    assert by_key['option-b']['state'] == 'open'


def test_exploratory_plan_never_auto_syncs(app):
    _, agent = modules()
    assert agent._trigger_post_mutation_sync('u', 't', {'planning_intent': 'exploratory', 'tasks': []}) == {
        'status': 'skipped', 'reason': 'exploratory_plan',
    }


def test_ai_task_tool_returns_invalid_date_error_without_saving(app, db, test_user, monkeypatch):
    strategy, agent = modules()
    tid = 'capture-invalid-task-date'
    _seed(db, test_user, tid, _cards())
    _fake_plan_build(strategy, agent, monkeypatch)
    built = agent._execute_mutation_tool(
        'generate_execution_plan', {'scorecard_id': 'card-b', 'planning_intent': 'exploratory'},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert built['ok'] is True, built
    task_id = built['project_wbs']['tasks'][0]['id']
    before = _plan(test_user, tid, 'card-b')

    result = agent._execute_mutation_tool(
        'update_wbs_task', {
            'task_id': task_id,
            'field': 'due_date',
            'new_value': '2026-11-102026-11-13',
        },
        user=test_user, user_id=test_user.id, thread_id=tid,
    )

    assert result == {
        'ok': False,
        'code': 'invalid_task_date',
        'error': f"Task '{task_id}' has an invalid due_date; expected YYYY-MM-DD.",
        'task_id': task_id,
        'field': 'due_date',
    }
    assert _plan(test_user, tid, 'card-b') == before


def test_two_conditions_from_one_quote_are_both_kept(app, db, test_user):
    from app.models_decision_record import DecisionSignal

    _, agent = modules()
    tid = 'capture-two-conditions'
    _seed(db, test_user, tid, _cards())
    message = 'Pursue Cherry Creek if we get bonding and insurance.'
    result = _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-c', 'disposition': 'pursue', 'user_request_quote': 'Pursue Cherry Creek',
         'conditions': [
             {'content': 'Bonding secured', 'user_quote': 'if we get bonding and insurance'},
             {'content': 'Insurance secured', 'user_quote': 'if we get bonding and insurance'},
         ]},
    ]}, message)
    ids = result['decisions'][0]['condition_signal_ids']
    assert len(set(ids)) == 2
    assert sorted(row.content for row in DecisionSignal.query.filter_by(kind='condition')) == [
        'Bonding secured', 'Insurance secured',
    ]

    both = 'Both bonding and insurance came through.'
    first, second = ids
    met_a = _call(agent, test_user, tid, 'record_decision_context', {
        'kind': 'condition', 'condition_signal_id': first, 'structured': {'status': 'met'},
        'user_request_quote': 'bonding and insurance came through',
    }, both)
    met_b = _call(agent, test_user, tid, 'record_decision_context', {
        'kind': 'condition', 'condition_signal_id': second, 'structured': {'status': 'met'},
        'user_request_quote': 'bonding and insurance came through',
    }, both)
    assert met_a['ok'] and met_b['ok'] and met_a['signal_id'] != met_b['signal_id']
    assert met_b['superseded_condition_id'] == second and met_b['created'] is True
    from app.decision_capture import decision_facts
    current = {c['content']: c['status'] for c in {
        o['option_key']: o for o in decision_facts(test_user, tid)['options']
    }['option-c']['conditions']}
    assert current == {'Bonding secured': 'met', 'Insurance secured': 'met'}


def test_bad_condition_fails_only_its_own_entry(app, db, test_user):
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'capture-condition-partial'
    _seed(db, test_user, tid, _cards())
    message = "We're going with Adams and Boulder, Boulder contingent on bonding."
    result = _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-a', 'disposition': 'pursue', 'user_request_quote': 'going with Adams'},
        {'option_key': 'option-b', 'disposition': 'pursue', 'user_request_quote': 'Boulder',
         'conditions': [{'content': 'Bonding', 'user_quote': 'pending a bond'}]},
    ]}, message)
    assert result['ok'] is True
    statuses = {item.get('option_key'): (item['status'], item.get('code')) for item in result['decisions']}
    assert statuses == {
        'option-a': ('recorded', None),
        'option-b': ('not_recorded', 'decision_condition_quote_required'),
    }
    # Boulder is never stored as an unconditional pursuit.
    assert [row.option_key for row in OptionDecision.query.all()] == ['option-a']


def test_condition_failure_status_card_never_shows_tool_text(app):
    _, agent = modules()
    action = {'tool': 'record_option_decision', 'result': {
        'ok': False, 'code': 'decision_condition_quote_required', 'non_blocking': True, 'option_names': [],
        'error': 'Each condition needs an exact quote',
    }}
    card = agent._artifact_entries_from_actions([action], user_message='x')[0]['artifact']['data']
    assert card['message'] == "This decision wasn't saved. Your message is saved."


def test_new_condition_needs_a_pursued_option_and_lapses_when_not_pursued(app, db, test_user):
    from app.decision_capture import decision_facts
    from app.decision_records import create_or_refresh_record, option_dispositions

    _, agent = modules()
    tid = 'capture-condition-scope'
    _seed(db, test_user, tid, _cards())
    no_option = _call(agent, test_user, tid, 'record_decision_context', {
        'kind': 'condition', 'content': 'Bonding', 'user_request_quote': 'if bonding works out',
    }, 'Only if bonding works out.')
    assert no_option['ok'] is False and no_option['code'] == 'condition_option_not_pursued'
    undecided = _call(agent, test_user, tid, 'record_decision_context', {
        'kind': 'condition', 'option_key': 'option-c', 'content': 'Bonding',
        'user_request_quote': 'if bonding works out',
    }, 'Cherry Creek only if bonding works out.')
    assert undecided['ok'] is False and undecided['code'] == 'condition_option_not_pursued'

    _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-c', 'disposition': 'pursue', 'user_request_quote': 'Pursue Cherry Creek',
         'conditions': [{'content': 'Bonding', 'user_quote': 'by Dec 1', 'due_by': '2026-12-01'}]},
    ]}, 'Pursue Cherry Creek if bonding is in place by Dec 1.')
    _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-c', 'disposition': 'not_pursue', 'user_request_quote': 'drop Cherry Creek'},
    ]}, "Let's drop Cherry Creek.")
    facts = decision_facts(test_user, tid, today=date(2026, 12, 5))
    option = {o['option_key']: o for o in facts['options']}['option-c']
    assert option['conditions'] == [] and 'conditional' not in option['disposition']
    assert not [f for f in facts['follow_up_facts'] if f['kind'] == 'condition_past_due']
    record, _ = create_or_refresh_record(test_user, tid)
    assert {o['option_key']: o for o in option_dispositions(record)['options']}['option-c']['conditions'] == {}


def test_plan_intent_is_required_in_the_schema(app):
    _, agent = modules()
    tool = next(
        item for item in agent._anthropic_tool_definitions(enable_mutation_tools=True)
        if item['name'] == 'generate_execution_plan'
    )
    assert tool['input_schema']['required'] == ['planning_intent']


def test_named_option_decides_which_plan_is_built(app, db, test_user, monkeypatch):
    from app.models_decision_record import OptionDecision

    strategy, agent = modules()
    tid = 'capture-plan-target'
    _seed(db, test_user, tid, _cards())
    _fake_plan_build(strategy, agent, monkeypatch)
    # An exploratory plan for Boulder leaves Boulder as the idea in view.
    agent._execute_mutation_tool(
        'generate_execution_plan', {'scorecard_id': 'card-b', 'planning_intent': 'exploratory'},
        user=test_user, user_id=test_user.id, thread_id=tid, view_context={'active_scorecard_id': 'card-b'},
    )
    built = agent._execute_mutation_tool(
        'generate_execution_plan', {'option_key': 'option-a', 'planning_intent': 'committed'},
        user=test_user, user_id=test_user.id, thread_id=tid, view_context={'active_scorecard_id': 'card-b'},
    )
    assert built['ok'] is True, built
    assert built['project_wbs']['scorecard_id'] == 'card-a'
    assert _plan(test_user, tid, 'card-a')['planning_intent'] == 'committed'
    assert _plan(test_user, tid, 'card-b')['planning_intent'] == 'exploratory'
    assert [(row.option_key, row.disposition) for row in OptionDecision.query.all()] == [('option-a', 'pursue')]

    missing = agent._execute_mutation_tool(
        'generate_execution_plan', {'option_key': 'option-zzz', 'planning_intent': 'committed'},
        user=test_user, user_id=test_user.id, thread_id=tid,
    )
    assert missing['ok'] is False and missing['code'] == 'decision_option_required'


def test_wrong_task_id_then_same_change_on_real_task_keeps_the_reply(app):
    _, agent = modules()
    wrong_id = {
        'tool': 'update_wbs_task',
        'input': {'task_id': 'task-guess', 'field': 'due_date', 'new_value': '2026-11-24'},
        'result': {'ok': False, 'code': 'task_not_found', 'error': 'Task not found.'},
    }
    landed = {
        'tool': 'update_wbs_task',
        'input': {'task_id': 'task-bond', 'field': 'due_date', 'new_value': '2026-11-24'},
        'result': {'ok': True, 'confirmation': "Updated task 'Bond letter' (due_date)."},
    }
    assert agent._apply_option_decision_failure_state(
        'Moved the bond letter to Nov 24.', [wrong_id, landed],
    ) == ('Moved the bond letter to Nov 24.', None)

    # A different value landing elsewhere doesn't excuse the failed change.
    other_value = {**landed, 'input': {**landed['input'], 'new_value': '2026-11-30'}}
    assert agent._apply_option_decision_failure_state(
        'Moved it.', [wrong_id, other_value],
    )[0] == ''


def test_a_real_failure_on_one_task_is_not_cleared_by_another_tasks_success(app):
    _, agent = modules()
    invalid_on_a = {
        'tool': 'update_wbs_task',
        'input': {'task_id': 'task-a', 'field': 'due_date', 'new_value': 'Nov 24'},
        'result': {'ok': False, 'code': 'invalid_task_date', 'error': 'invalid'},
    }
    saved_on_b = {
        'tool': 'update_wbs_task',
        'input': {'task_id': 'task-b', 'field': 'due_date', 'new_value': 'Nov 24'},
        'result': {'ok': True, 'confirmation': "Updated task 'B' (due_date)."},
    }
    reply, failure = agent._apply_option_decision_failure_state('Both moved.', [invalid_on_a, saved_on_b])
    assert reply == ''
    assert failure['code'] == 'invalid_task_date'
