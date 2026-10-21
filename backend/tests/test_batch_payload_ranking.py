"""Viewing a batch upload whose ranking recorded usage must not crash (NameError on `user`)."""
import json
import sys


def test_batch_payload_with_ranking_usage_renders(app):
    agent = sys.modules['app.routes.ai_agent']
    from app.models import BatchIdeaUpload
    batch = BatchIdeaUpload(
        ideas_json='[]',
        ranking_result_json=json.dumps({
            'model_type': 'orbit',
            'usage': {'provider': 'anthropic', 'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15},
            'credits': {'charged': 1, 'remaining': 99},
        }),
    )
    with app.test_request_context():
        payload = agent._visible_batch_payload(batch)
    assert isinstance(payload, dict)
