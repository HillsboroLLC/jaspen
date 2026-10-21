"""W11: neutral values are explained after queued (multi-option) scoring."""
from tests.test_decision_flow_stabilization import modules, seed_rfp_thread


def _score_with(monkeypatch, neutral_by_name):
    _, agent = modules()

    def score_one(_tool, tool_input, **_kwargs):
        name = tool_input['name']
        scorecard = {
            'id': f'card-{name}', 'project_name': name, 'jaspen_score': 56,
            'neutral_criteria': [{'key': label.lower(), 'label': label, 'score': 45} for label in neutral_by_name.get(name, [])],
        }
        return {'ok': True, 'scorecard': scorecard, 'artifact': {'type': 'scorecard', 'data': scorecard}}

    monkeypatch.setattr(agent, '_execute_mutation_tool', score_one)
    return agent


def _notes(agent, user_id, tid):
    history = agent.load_user_sessions(user_id)[tid]['chat_history']
    return [item['content'] for item in history if 'neutral 45' in str(item.get('content') or '')]


def test_one_note_after_the_last_option_names_the_shared_neutral_criteria(client, test_user, auth_headers, monkeypatch):
    tid = 'queued-neutral-shared'
    seed_rfp_thread(test_user, tid, queue=[{'name': 'Agency'}, {'name': 'Hire'}])
    agent = _score_with(monkeypatch, {'Agency': ['Speed to results', 'Switching cost'], 'Hire': ['Speed to results', 'Switching cost']})

    client.post(f'/api/v1/strategy/threads/{tid}/score-next', headers=auth_headers, json={'name': 'Agency'})
    assert _notes(agent, test_user.id, tid) == []  # not until the batch is done
    client.post(f'/api/v1/strategy/threads/{tid}/score-next', headers=auth_headers, json={'name': 'Hire'})

    assert _notes(agent, test_user.id, tid) == [
        "Some criteria had no information yet, so Jaspen used a neutral 45 (labeled Assumed) for them: "
        "Speed to results and Switching cost. A neutral value neither helps nor hurts an option; it holds the "
        "place until you share what you know. Want to fill these in? I can ask about them one at a time."
    ]
    assert 'queue_neutral_criteria' not in agent.load_user_sessions(test_user.id)[tid]


def test_note_lists_neutral_criteria_per_option_when_they_differ(client, test_user, auth_headers, monkeypatch):
    tid = 'queued-neutral-differ'
    seed_rfp_thread(test_user, tid, queue=[{'name': 'Agency'}, {'name': 'Hire'}])
    agent = _score_with(monkeypatch, {'Agency': ['Switching cost'], 'Hire': ['Ramp-up time', 'Retention risk']})
    for name in ('Agency', 'Hire'):
        client.post(f'/api/v1/strategy/threads/{tid}/score-next', headers=auth_headers, json={'name': name})
    notes = _notes(agent, test_user.id, tid)
    assert len(notes) == 1
    assert 'Agency: Switching cost; Hire: Ramp-up time and Retention risk.' in notes[0]


def test_no_note_when_nothing_was_neutral(client, test_user, auth_headers, monkeypatch):
    tid = 'queued-neutral-none'
    seed_rfp_thread(test_user, tid, queue=[{'name': 'Agency'}, {'name': 'Hire'}])
    agent = _score_with(monkeypatch, {})
    for name in ('Agency', 'Hire'):
        client.post(f'/api/v1/strategy/threads/{tid}/score-next', headers=auth_headers, json={'name': name})
    assert _notes(agent, test_user.id, tid) == []
