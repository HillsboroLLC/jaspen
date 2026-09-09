from unittest.mock import Mock, patch

from flask import Flask

from app.routes.outreach_intelligence import outreach_intelligence_bp


def make_client():
    app = Flask(__name__)
    app.register_blueprint(
        outreach_intelligence_bp, url_prefix="/api/v1/outreach-intelligence"
    )
    app.testing = True
    return app.test_client()


def test_qualify_requires_shared_secret():
    response = make_client().post(
        "/api/v1/outreach-intelligence/qualify", json={"prospect": {}, "evidence": []}
    )
    assert response.status_code == 401


@patch("app.routes.outreach_intelligence.requests.post")
def test_qualify_forwards_json_and_secret(mock_post):
    upstream = Mock()
    upstream.status_code = 200
    upstream.json.return_value = {"overall_qualification": "Low"}
    mock_post.return_value = upstream

    payload = {"prospect": {"id": "p1"}, "evidence": [{"id": "e1"}]}
    response = make_client().post(
        "/api/v1/outreach-intelligence/qualify",
        headers={"X-Jaspen-Outreach-Secret": "test-secret"},
        json=payload,
    )

    assert response.status_code == 200
    assert response.get_json()["overall_qualification"] == "Low"
    _, kwargs = mock_post.call_args
    assert kwargs["headers"]["X-Jaspen-Outreach-Secret"] == "test-secret"
    assert kwargs["json"] == payload
