"""Batch scoring runs one model call per option, concurrently.

Five options in a single call ran past the provider timeout and the gunicorn
worker limit, so no scorecards were produced. These tests pin the per-option,
parallel shape and the positional alignment the score-batch route relies on.
"""
import json
import re
import sys
import threading
import time


RUBRIC = {
    'criteria': [
        {'key': 'fit', 'label': 'Founder fit', 'weight': 0.6},
        {'key': 'speed', 'label': 'Time to signal', 'weight': 0.4},
    ]
}
SCORES = {'Alpha': 90, 'Bravo': 70, 'Charlie': 60, 'Delta': 80, 'Echo': 50}  # raw model scores


def _fake_reply_factory(calls, delay=0.0, fail=()):
    lock = threading.Lock()

    def fake(messages, **_kwargs):
        name = re.search(r'1\. "([^"]+)"', messages[0]['content']).group(1)
        with lock:
            calls.append(name)
        if delay:
            time.sleep(delay)
        if name in fail:
            raise RuntimeError('provider failed')
        score = SCORES[name]
        dims = {key: {'score': score, 'confidence': 'medium', 'rationale': 'r'} for key in ('fit', 'speed')}
        usage = {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15, 'provider': 'anthropic', 'model': 'm'}
        return json.dumps({'options': [{'name': name, 'primary_role': f'role-{name}', 'dimensions': dims}]}), usage

    return fake


def _strategy_module():
    return sys.modules['app.routes.strategy']


def test_each_option_is_scored_in_its_own_concurrent_call(app, monkeypatch):
    strategy = _strategy_module()
    calls = []
    monkeypatch.setattr(strategy, '_strategy_generate_reply', _fake_reply_factory(calls, delay=0.5))
    names = list(SCORES)

    with app.app_context():
        started = time.monotonic()
        cards, summary, usage = strategy._generate_batch_scorecards(
            None, [{'name': n} for n in names], rubric=RUBRIC,
            model_selection={'model_type': 'orbit'}, return_usage=True,
        )
        elapsed = time.monotonic() - started

    assert sorted(calls) == sorted(names)          # one call per option
    assert elapsed < 1.5                            # concurrent, not 5 x 0.5s
    assert [card['primary_role'] for card in cards] == [f'role-{n}' for n in names]
    assert usage['total_tokens'] == 15 * len(names)
    assert summary['recommended_sequence'].startswith('Commit first to ')
    assert 'Founder fit' in summary['recommended_sequence']


def test_a_failed_option_keeps_the_others_aligned(app, monkeypatch):
    strategy = _strategy_module()
    monkeypatch.setattr(strategy, '_strategy_generate_reply', _fake_reply_factory([], fail={'Bravo'}))
    names = list(SCORES)

    with app.app_context():
        cards, _summary, _usage = strategy._generate_batch_scorecards(
            None, [{'name': n} for n in names], rubric=RUBRIC,
            model_selection={'model_type': 'orbit'}, return_usage=True,
        )

    assert [card['primary_role'] if card else None for card in cards] == [
        'role-Alpha', None, 'role-Charlie', 'role-Delta', 'role-Echo',
    ]
