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
    assert result['receipts'] == [
        'Decision recorded: Moving forward with Adams County Bid.',
        'Decision recorded: Moving forward with Boulder Transit Bid.',
    ]
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
    assert result['receipts'] == ['Recorded: Still evaluating Cherry Creek Bid.']

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


def test_override_requires_confirmation_with_facts_only_then_records(app, db, test_user):
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'capture-override'
    cards = _cards()
    cards[2]['recommendation'] = {'verdict_key': 'decline', 'label': 'No-Bid'}
    _seed(db, test_user, tid, cards)
    first_message = "We're bidding on Cherry Creek and Adams anyway."
    _set_history(test_user, tid, [{'role': 'user', 'content': first_message}])
    first = _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-c', 'disposition': 'pursue', 'user_request_quote': 'bidding on Cherry Creek'},
        {'option_key': 'option-a', 'disposition': 'pursue', 'user_request_quote': 'Adams anyway'},
    ]}, first_message)

    assert first['ok'] is True
    assert first['confirmation_required'] is True
    assert 'confirmation' not in first
    statuses = {item['option_key']: item['status'] for item in first['decisions']}
    assert statuses == {'option-c': 'confirmation_required', 'option-a': 'recorded'}
    assert first['receipts'] == ['Decision recorded: Moving forward with Adams County Bid.']
    card = first['artifact']['data']
    assert card['kind'] == 'decision_override'
    assert [a['label'] for a in card['actions']] == ['Record override', 'Cancel']
    assert first['pending_option_decisions']['option-c']['override_of'] == 'decline'
    _assert_no_customer_wording(first)
    assert OptionDecision.query.filter_by(option_key='option-c').count() == 0

    confirm = 'Yes, record it.'
    _set_history(test_user, tid, [
        {'role': 'user', 'content': first_message},
        {'role': 'assistant', 'content': 'Jaspen recommended No-Bid on Cherry Creek. Record it anyway'},
        {'role': 'user', 'content': confirm},
    ])
    second = _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {'option_key': 'option-c', 'disposition': 'pursue', 'user_request_quote': confirm},
    ]}, confirm)
    assert second['ok'] is True and not second.get('confirmation_required')
    row = OptionDecision.query.filter_by(option_key='option-c').one()
    assert row.user_quote == 'bidding on Cherry Creek'
    assert row.override_info['override_of'] == 'decline'
    assert row.capture_metadata['override_confirmation_quote'] == confirm
    assert second['pending_option_decisions'] == {}


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
    assert result['confirmation'] == 'Decision recorded: Deferred Boulder Transit Bid.'


def test_context_signals_commitment_review_and_retraction(app, db, test_user):
    from app.decision_capture import decision_facts
    from app.models_decision_record import DecisionSignal

    _, agent = modules()
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
    assert result['task_commitment']['task_due_date_differs'] is True
    task = next(item for item in _plan(test_user, tid, 'card-a')['tasks'] if item['id'] == 't1')
    assert task['commitment']['basis'] == 'user_stated'
    assert task['commitment']['due_date'] == '2026-11-20'
    assert task['commitment']['ref'] == result['signal_id']
    assert task['due_date'] == '2026-11-18'
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
    assert result['receipts'] == ['Commitment recorded: Kickoff.']

    again = _call(agent, test_user, tid, 'confirm_task_commitment', {
        'task_id': 't9', 'option_key': 'option-b', 'user_request_quote': 'still December 1',
    }, 'still December 1')
    assert again['already_committed'] is True and again['receipts'] == []
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
    assert met['receipts'] == ['Outcome recorded: Achieved for Adams County Bid.']

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
            '_decision_facts_prompt_suffix', '_pending_override_facts',
        )
    ]
    combined = '\n'.join(sources)
    for banned in (
        "record it?", "which option did you mean", "That overrides Jaspen's No-Bid",
        "A confirmation card is shown; ask", "Would you like", "Do you want",
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


def test_unconfirmed_override_expires_and_same_turn_repeat_never_self_confirms(app, db, test_user):
    from app.models_decision_record import OptionDecision

    _, agent = modules()
    tid = 'capture-override-expiry'
    cards = _cards()
    cards[2]['recommendation'] = {'verdict_key': 'decline', 'label': 'No-Bid'}
    _seed(db, test_user, tid, cards)
    first = "We're bidding on Cherry Creek."
    _set_history(test_user, tid, [{'role': 'user', 'content': first}])
    entry = {'option_key': 'option-c', 'disposition': 'pursue', 'user_request_quote': 'bidding on Cherry Creek'}
    assert _call(agent, test_user, tid, 'record_option_decision', {'decisions': [entry]}, first)['confirmation_required']
    repeat = _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {**entry, 'user_request_quote': 'Cherry Creek'},
    ]}, first)
    assert repeat['confirmation_required'] is True
    assert OptionDecision.query.count() == 0

    later = 'Ok fine, go with Cherry Creek.'
    _set_history(test_user, tid, [
        {'role': 'user', 'content': first},
        {'role': 'user', 'content': "No, don't record it."},
        {'role': 'user', 'content': later},
    ])
    result = _call(agent, test_user, tid, 'record_option_decision', {'decisions': [
        {**entry, 'user_request_quote': 'go with Cherry Creek'},
    ]}, later)
    assert result['confirmation_required'] is True
    assert result['pending_option_decisions']['option-c']['user_request_quote'] == 'go with Cherry Creek'
    assert OptionDecision.query.count() == 0


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
    assert 'receipts' in types
    status = next(item['artifact']['data'] for item in entries if item['artifact']['type'] == 'status')
    assert [a['value'] for a in status['actions']] == ['Adams County Bid', 'Adams Rail Bid']


def test_capture_only_turns_offer_no_undo(app):
    _, agent = modules()
    assert not agent._has_undoable_mutations([{'tool': 'record_lesson', 'success': True}])
    assert not agent._has_undoable_mutations([{'tool': 'record_option_decision', 'success': True}])
    assert agent._has_undoable_mutations([{'tool': 'confirm_task_commitment', 'success': True}])
    assert agent._has_undoable_mutations([{'tool': 'update_wbs_task', 'success': True}])
