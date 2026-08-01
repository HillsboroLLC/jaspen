import uuid
from dataclasses import dataclass

from flask_jwt_extended import create_access_token
from werkzeug.security import generate_password_hash

from app.models import (
    DecisionAssetEmail,
    Organization,
    Scorecard,
    UsageEvent,
    User,
    UserSession,
)


@dataclass
class _Result:
    provider: str = "test"
    response_category: str = "accepted"


class _Provider:
    def __init__(self, fail_count=0):
        self.fail_count = fail_count
        self.messages = []

    def send(self, **message):
        self.messages.append(message)
        if self.fail_count:
            self.fail_count -= 1
            raise RuntimeError("provider unavailable and sensitive detail")
        return _Result()


def _scorecard_data(name, score, dimension_score):
    return {
        "project_name": name,
        "name": name,
        "jaspen_score": score,
        "score_category": "Good",
        "executive_summary": f"{name} has the best current balance of value and execution readiness.",
        "dimensions": {
            "strategic_fit": {"label": "Strategic fit", "score": dimension_score},
            "execution_readiness": {"label": "Execution readiness", "score": dimension_score - 1},
        },
        "assumptions": ["Demand remains stable."],
        "evidence_gaps": ["Confirm customer adoption data."],
        "top_risks": ["Delivery ownership is not confirmed."],
        "what_could_change_order": ["Validated adoption data could change the ranking."],
        "recommendations": ["Confirm ownership and validate adoption before launch."],
    }


def _wbs():
    return {
        "name": "Starter execution plan",
        "start_date": "2026-08-03",
        "phases": [{"name": "Validate", "task_ids": ["task-1"]}],
        "tasks": [{
            "id": "task-1",
            "title": "Validate customer adoption",
            "phase": "Validate",
            "status": "todo",
            "priority": "high",
            "owner": "Decision owner",
            "start_date": "2026-08-03",
            "due_date": "2026-08-07",
            "depends_on": [],
        }],
    }


def _seed_decision(db, user, *, thread_id="thread-email", organization_id=None, include_wbs=True):
    user.email_verified = True
    user.email_verified_at = None
    session = UserSession(
        user_id=user.id,
        session_id=thread_id,
        name="Market entry decision",
        organization_id=organization_id,
        created_by_user_id=user.id,
        payload={"session_id": thread_id, "name": "Market entry decision", "organization_id": organization_id},
        scenarios_json={
            "wbs_by_scorecard": {"option-a": _wbs()} if include_wbs else {},
            "project_wbs": _wbs() if include_wbs else None,
        },
    )
    first = Scorecard(
        id="option-a",
        user_id=user.id,
        organization_id=organization_id,
        thread_id=thread_id,
        evaluation_id=str(uuid.uuid4()),
        project_name="Option A",
        score=82,
        assumptions=["Demand remains stable."],
        evidence=[],
        data=_scorecard_data("Option A", 82, 9),
    )
    second = Scorecard(
        id="option-b",
        user_id=user.id,
        organization_id=organization_id,
        thread_id=thread_id,
        evaluation_id=str(uuid.uuid4()),
        project_name="Option B",
        score=68,
        assumptions=[],
        evidence=[],
        data=_scorecard_data("Option B", 68, 6),
    )
    db.session.add_all([session, first, second])
    db.session.commit()
    return first


def _sync_worker(monkeypatch):
    from app import decision_asset_email_service as service
    monkeypatch.setattr(
        "app.routes.decision_asset_email.start_delivery",
        lambda delivery_id: service.process_delivery(delivery_id),
    )


def _request(client, headers, key, *, thread_id="thread-email", output_types=None):
    return client.post(
        f"/api/v1/email-assets/threads/{thread_id}",
        headers=headers,
        json={
            "idempotency_key": key,
            "scorecard_id": "option-a",
            "output_types": output_types or [
                "ranked_ideas",
                "scorecards",
                "why_this_order",
                "evidence_gaps_assumptions_risks",
                "what_could_change_order",
            ],
        },
    )


def test_success_sends_only_verified_recipient_with_summary_and_existing_assets(
    app, client, db, test_user, auth_headers, monkeypatch,
):
    _seed_decision(db, test_user)
    provider = _Provider()
    monkeypatch.setattr("app.decision_asset_email_service.get_transactional_email_provider", lambda: provider)
    _sync_worker(monkeypatch)
    credits_before = test_user.credits_remaining

    recipient = client.get("/api/v1/email-assets/recipient", headers=auth_headers)
    assert recipient.status_code == 200
    assert recipient.json == {"recipient_masked": "t**t@example.com"}

    response = _request(client, auth_headers, "email-success-0001")
    assert response.status_code == 202
    assert response.json["status"] == "sent"
    assert response.json["recipient_masked"] == "t**t@example.com"
    assert len(provider.messages) == 1
    message = provider.messages[0]
    assert message["recipient"] == test_user.email
    assert "WHY THIS ORDER" in message["text_body"]
    assert "1. Option A (82)" in message["text_body"]
    assert "2. Option B (68)" in message["text_body"]
    assert "Evidence gaps" in message["text_body"]
    assert "What could change the order" in message["text_body"]
    assert {item.content_type for item in message["attachments"]} == {
        "application/pdf",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }
    assert all(item.data for item in message["attachments"])
    assert User.query.get(test_user.id).credits_remaining == credits_before
    telemetry = UsageEvent.query.order_by(UsageEvent.id).all()
    assert [event.operation_type for event in telemetry] == [
        "email_assets_requested",
        "email_assets_sent",
    ]
    assert all(event.evaluation_id for event in telemetry)
    assert all(event.credits_charged == 0 for event in telemetry)

    # Existing authenticated export remains available after an email send.
    download = client.get(
        "/api/v1/export/threads/thread-email/scorecard/pdf?scorecard_id=option-a",
        headers=auth_headers,
    )
    assert download.status_code == 200
    assert download.data.startswith(b"%PDF-")


def test_unverified_user_cannot_request_email(client, db, test_user, auth_headers):
    _seed_decision(db, test_user)
    test_user.email_verified = False
    db.session.commit()
    response = _request(client, auth_headers, "email-unverified-1")
    assert response.status_code == 403
    assert response.json["code"] == "verified_email_required"


def test_unauthorized_thread_and_scorecard_are_not_disclosed(client, db, test_user, auth_headers):
    _seed_decision(db, test_user)
    missing_thread = _request(client, auth_headers, "email-missing-thread", thread_id="someone-elses-thread")
    assert missing_thread.status_code == 404

    response = client.post(
        "/api/v1/email-assets/threads/thread-email",
        headers=auth_headers,
        json={
            "idempotency_key": "email-missing-scorecard",
            "scorecard_id": "someone-elses-scorecard",
            "output_types": ["scorecards"],
        },
    )
    assert response.status_code == 404
    assert response.json["code"] == "scorecard_not_found"


def test_cross_workspace_access_is_rejected(client, db, test_user, auth_headers):
    organization = Organization(name="Former workspace", plan_key="team")
    db.session.add(organization)
    db.session.flush()
    _seed_decision(db, test_user, organization_id=organization.id)
    response = _request(client, auth_headers, "email-cross-workspace")
    assert response.status_code == 403
    assert response.json["code"] == "workspace_access_denied"


def test_missing_execution_plan_fails_without_losing_delivery(
    client, db, test_user, auth_headers, monkeypatch,
):
    _seed_decision(db, test_user, include_wbs=False)
    provider = _Provider()
    monkeypatch.setattr("app.decision_asset_email_service.get_transactional_email_provider", lambda: provider)
    _sync_worker(monkeypatch)
    response = _request(
        client,
        auth_headers,
        "email-missing-plan",
        output_types=["starter_execution_plan", "why_this_order"],
    )
    assert response.status_code == 202
    assert response.json["status"] == "failed"
    assert response.json["error_category"] == "execution_plan_not_found"
    assert provider.messages == []
    assert DecisionAssetEmail.query.one().status == "failed"


def test_execution_plan_request_attaches_existing_excel(
    client, db, test_user, auth_headers, monkeypatch,
):
    _seed_decision(db, test_user, include_wbs=True)
    provider = _Provider()
    monkeypatch.setattr("app.decision_asset_email_service.get_transactional_email_provider", lambda: provider)
    _sync_worker(monkeypatch)
    response = _request(
        client,
        auth_headers,
        "email-execution-plan",
        output_types=["starter_execution_plan", "why_this_order"],
    )
    assert response.json["status"] == "sent"
    assert len(provider.messages) == 1
    attachments = provider.messages[0]["attachments"]
    assert len(attachments) == 1
    assert attachments[0].content_type == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert attachments[0].filename.endswith("-execution-plan.xlsx")
    assert attachments[0].data.startswith(b"PK")


def test_artifact_generation_failure_is_classified_without_sensitive_content(
    client, db, test_user, auth_headers, monkeypatch,
):
    _seed_decision(db, test_user)
    provider = _Provider()
    monkeypatch.setattr("app.decision_asset_email_service.get_transactional_email_provider", lambda: provider)
    monkeypatch.setattr(
        "app.decision_asset_email_service._scorecard_pdf_bytes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("secret artifact detail")),
    )
    _sync_worker(monkeypatch)
    response = _request(client, auth_headers, "email-artifact-failure")
    assert response.json["status"] == "failed"
    assert response.json["error_category"] == "artifact_generation_failed"
    assert "secret" not in str(response.json).lower()
    assert provider.messages == []


def test_provider_failure_can_retry_with_same_idempotency_key(
    client, db, test_user, auth_headers, monkeypatch,
):
    _seed_decision(db, test_user)
    provider = _Provider(fail_count=1)
    monkeypatch.setattr("app.decision_asset_email_service.get_transactional_email_provider", lambda: provider)
    _sync_worker(monkeypatch)

    first = _request(client, auth_headers, "email-retry-provider")
    assert first.json["status"] == "failed"
    assert first.json["error_category"] == "provider_failure"
    second = _request(client, auth_headers, "email-retry-provider")
    assert second.status_code == 202
    assert second.json["status"] == "sent"
    assert len(provider.messages) == 2
    assert DecisionAssetEmail.query.one().attempts == 2
    assert UsageEvent.query.filter_by(operation_type="email_assets_failed").count() == 1
    assert UsageEvent.query.filter_by(operation_type="email_assets_sent").count() == 1


def test_duplicate_success_is_idempotent(client, db, test_user, auth_headers, monkeypatch):
    _seed_decision(db, test_user)
    provider = _Provider()
    monkeypatch.setattr("app.decision_asset_email_service.get_transactional_email_provider", lambda: provider)
    _sync_worker(monkeypatch)
    first = _request(client, auth_headers, "email-idempotent-1")
    second = _request(client, auth_headers, "email-idempotent-1")
    assert first.json["delivery_id"] == second.json["delivery_id"]
    assert second.status_code == 200
    assert len(provider.messages) == 1
    assert DecisionAssetEmail.query.count() == 1


def test_database_rate_limit_rejects_new_request(client, app, db, test_user, auth_headers, monkeypatch):
    _seed_decision(db, test_user)
    provider = _Provider()
    monkeypatch.setattr("app.decision_asset_email_service.get_transactional_email_provider", lambda: provider)
    _sync_worker(monkeypatch)
    original_limit = app.config["DECISION_ASSET_EMAIL_RATE_LIMIT_PER_HOUR"]
    app.config["DECISION_ASSET_EMAIL_RATE_LIMIT_PER_HOUR"] = 1
    try:
        assert _request(client, auth_headers, "email-rate-limit-1").status_code == 202
        limited = _request(client, auth_headers, "email-rate-limit-2")
        assert limited.status_code == 429
        assert limited.json["code"] == "email_assets_rate_limited"
    finally:
        app.config["DECISION_ASSET_EMAIL_RATE_LIMIT_PER_HOUR"] = original_limit


def test_delivery_status_is_scoped_to_authenticated_user(app, client, db, test_user, auth_headers, monkeypatch):
    _seed_decision(db, test_user)
    provider = _Provider()
    monkeypatch.setattr("app.decision_asset_email_service.get_transactional_email_provider", lambda: provider)
    _sync_worker(monkeypatch)
    created = _request(client, auth_headers, "email-status-scope")

    other = User(
        email="other@example.com",
        name="Other User",
        password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
        subscription_plan="free",
        credits_remaining=300,
        email_verified=True,
    )
    db.session.add(other)
    db.session.commit()
    with app.app_context():
        token = create_access_token(identity=str(other.id))
    response = client.get(
        f"/api/v1/email-assets/{created.json['delivery_id']}",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 404


def test_smtp_provider_uses_configured_sender_reply_to_and_both_bodies(app, monkeypatch):
    from app.email_provider import TransactionalEmailProvider

    sent = []
    monkeypatch.setattr("app.email_provider.mail.send", lambda message: sent.append(message))
    with app.app_context():
        monkeypatch.setitem(app.config, "MAIL_DEFAULT_SENDER", "configured@example.test")
        monkeypatch.setitem(app.config, "DECISION_ASSET_EMAIL_SENDER_NAME", "Jaspen Results")
        monkeypatch.setitem(app.config, "DECISION_ASSET_EMAIL_REPLY_TO", "reply@example.test")
        result = TransactionalEmailProvider().send(
            subject="Decision result",
            recipient="verified@example.test",
            text_body="Plain result",
            html_body="<p>HTML result</p>",
        )
    assert result.provider == "smtp"
    assert len(sent) == 1
    assert sent[0].recipients == ["verified@example.test"]
    assert sent[0].sender == "Jaspen Results <configured@example.test>"
    assert sent[0].reply_to == "reply@example.test"
    assert sent[0].body == "Plain result"
    assert sent[0].html == "<p>HTML result</p>"
