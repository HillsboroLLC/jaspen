import json

import pytest

from tests.test_decision_flow_stabilization import modules


@pytest.fixture
def inline_plan_jobs(monkeypatch):
    strategy, _ = modules()
    monkeypatch.setattr(strategy, '_start_plan_build_job', strategy._run_plan_build_job)


@pytest.fixture
def scripted_plan_provider(monkeypatch):
    def install(plan, hook=None):
        strategy, _ = modules()

        def provider(_messages, **_kwargs):
            if hook is not None:
                hook()
            return json.dumps(plan), {
                'provider': 'scripted', 'input_tokens': 10,
                'output_tokens': 5, 'total_tokens': 15,
            }

        monkeypatch.setattr(strategy, '_strategy_generate_reply', provider)
        return provider
    return install
