"""I4 PostgreSQL journeys: a modern organization's AI work runs through Phase 12 and the delivery worker.

These are the modern counterparts of the eight strict-xfail F2-F4 probes in
``journeys/test_conversation_turn_lifecycle.py``. Those probes keep pinning the
legacy path, which OD-1 Option C leaves unchanged. Here the same customer
promises hold for a modern organization (Product Contract 7.5: never charged for
a failure, never twice):

* F2: a reply that cannot be saved is not charged;
* F3 / gate criterion 1: a dropped stream neither strands nor charges a
  reservation; the worker keeps going, saves the reply and settles it once;
* F4: a rollback inside generation neither adds credits on failure nor loses
  the charge on success.

No provider is called: generation goes through the real provider adapter with a
fake client, so the call observer and Phase 12 see every request.
"""

import os
import time
import uuid

import pytest
import sqlalchemy as sa
from werkzeug.security import generate_password_hash

from app import db as _db
from app import billing_cutover as bc
from app import billing_runtime_funding as funding
from app import billing_runtime_policies as policies
from app.ai_providers import anthropic as anthropic_provider
from app.models import CreditLedgerEntry, CreditLot, Organization, OrganizationMember, User, UserSession
from app.models_billing_phase12 import AIBillingOperation
from tests.test_ai_provider_observer import FakeClient


pytestmark = [pytest.mark.postgres, pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"), reason="local disposable PostgreSQL is not configured")]

ALL = "identity,financial_events,credit_funding,ai_reservation,readers"
CONTINUE_URL = "/api/v1/ai-agent/conversation/continue"
REPLY = "What outcome and time horizon should guide this decision?"
MODEL = "claude-sonnet-5"
RULES = {
    "pricing": {"rates": [{"provider": "anthropic", "model": MODEL, "input_rate": "2", "output_rate": "10"}],
                "source_reference": "i4-test"},
    "capacity": {
        "schema": "jaspen.capacity.v1",
        "tiers": {"plan.free": {"priority": 1, "member": {"max_concurrent": 3, "windows": [
            {"key": "five_hour", "window_seconds": 18000, "max_operations": 50}]}}},
        "runaway": {"max_provider_attempts": 3, "max_tool_iterations": 8, "max_operation_seconds": 120,
                    "reservation_lease_seconds": 300, "max_reserved_credits": 3600000,
                    "max_call_input_tokens": 150000, "max_call_output_tokens": 16000,
                    "max_operation_tokens": 400000},
    },
}
# FakeClient reports 11 input and 7 output tokens: 11 x $2/M + 7 x $10/M at 3,600,000 units per USD.
CHARGE = 332


@pytest.fixture(autouse=True)
def _no_rate_limits():
    from app import limiter
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


@pytest.fixture
def modern(app, db, monkeypatch):
    monkeypatch.setenv(bc.SETTING, ALL)
    session = db.session
    owner = User(email=f"i4-{uuid.uuid4().hex[:8]}@example.invalid", name="Owner",
                 password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
                 subscription_plan="free", credits_remaining=0, seat_limit=1, max_seats=1)
    session.add(owner)
    session.flush()
    org = Organization(name="Modern", slug=f"modern-{uuid.uuid4().hex[:8]}", owner_user_id=owner.id, plan_key="free")
    session.add(org)
    session.flush()
    session.add(OrganizationMember(organization_id=org.id, user_id=owner.id, role="owner", status="active"))
    owner.active_organization_id = org.id
    session.commit()
    assignment, _state = bc.establish_modern_billing_identity(
        session, organization_id=org.id, actor_user_id=owner.id, currency="usd", origin_type="test",
        origin_id="i4-journey")
    session.commit()
    from datetime import timedelta
    funding.define_test_catalog(session, approver_user_id=owner.id, app_config=app.config,
                                effective_at=bc._database_now(session) - timedelta(days=400))
    session.commit()
    allocation = funding.allocate_free(
        session, bc.modern_context(session, family="credit_funding", organization_id=org.id))
    session.commit()
    assert allocation.outcome in {"inserted", "replayed", "allocated", "opened"}, allocation
    policies.install_test_policies(session, rules=RULES, approval_reference="i4-test")
    session.commit()
    from flask_jwt_extended import create_access_token
    with app.app_context():
        headers = {"Authorization": f"Bearer {create_access_token(identity=str(owner.id))}"}
    from app.routes.sessions import save_user_sessions
    thread = f"t-{uuid.uuid4().hex[:8]}"
    assert save_user_sessions(owner.id, {thread: {
        "session_id": thread, "user_id": owner.id, "name": "Project", "status": "in_progress",
        "chat_history": [{"role": "user", "content": "Question"}, {"role": "assistant", "content": "Answer"}],
    }})
    yield {"owner": owner, "org": org, "account": assignment.billing_account_id, "headers": headers,
           "thread": thread}
    _wait_idle(session)


def _wait_idle(session, timeout=20):
    from app.models_billing_delivery import AIDeliveryJob
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        session.rollback()
        if not session.query(AIDeliveryJob).filter(AIDeliveryJob.state != "finished").count():
            return
        time.sleep(0.1)


def _provider_reply(during=None, fail_with=None):
    """One real adapter request (observed and priced), then the scripted reply."""
    anthropic_provider.message_create(FakeClient(), candidates=[MODEL], max_tokens=500,
                                      messages=[{"role": "user", "content": "q"}])
    if during is not None:
        during()
    if fail_with is not None:
        raise fail_with
    return REPLY, {"provider": "anthropic", "model": MODEL, "input_tokens": 11, "output_tokens": 7,
                   "total_tokens": 18}, [], [], None


def _script(monkeypatch, **kwargs):
    from app.routes import ai_agent

    def generate(*_a, **_k):
        return _provider_reply(**kwargs)

    def stream(*_a, state=None, **_k):
        # Text arrives during a provider request, as in a real stream.
        reply, usage, actions, mutations, undo = _provider_reply(**kwargs)
        yield {"type": "delta", "text": REPLY[:10]}
        yield {"type": "delta", "text": REPLY[10:]}
        state.update(reply=reply, usage=usage, actions=actions, mutations=mutations, undo_snapshot=undo)

    monkeypatch.setattr(ai_agent, "_generate_assistant_reply", generate)
    monkeypatch.setattr(ai_agent, "_stream_assistant_reply_events", stream)
    monkeypatch.setattr(ai_agent, "_classify_decision_kit", lambda *_a, **_k: {
        "kit": "none", "confidence": "high", "evidence_quote": ""})


def _spendable(session, account):
    session.rollback()
    lots = [lot.id for lot in session.query(CreditLot).filter_by(billing_account_id=account)]
    rows = session.query(CreditLedgerEntry).filter(CreditLedgerEntry.lot_id.in_(lots)).all()
    return sum(r.available_delta for r in rows), sum(r.held_delta for r in rows)


def _operations(session, org):
    session.rollback()
    return session.query(AIBillingOperation).filter_by(organization_id=org.id).all()


def _history(session, thread):
    session.rollback()
    row = session.query(UserSession).filter_by(session_id=thread).one()
    return [m.get("content") for m in (row.payload or {}).get("chat_history") or []]


def test_a_modern_json_turn_is_charged_its_delivered_usage_once(client, db, modern, monkeypatch):
    _script(monkeypatch)
    before, _held = _spendable(db.session, modern["account"])
    response = client.post(CONTINUE_URL, headers=modern["headers"],
                           json={"thread_id": modern["thread"], "message": "Should we bid?"})
    assert response.status_code == 200, response.get_json()
    after, held = _spendable(db.session, modern["account"])
    assert (before - after, held) == (CHARGE, 0)
    [operation] = _operations(db.session, modern["org"])
    assert (operation.state, operation.delivery_status) == ("finalized", "delivered")
    assert REPLY in _history(db.session, modern["thread"])
    # No legacy charge: no P4.0 turn claim and no legacy credits recorded. (The per-user compatibility counter
    # may still be reset on read by legacy code; it is never debited for a modern turn.)
    from app.ai_audit import TURN_LIFECYCLE_VERSION
    from app.models import AIOperation, UsageEvent
    legacy_claims = [op for op in db.session.query(AIOperation).filter_by(user_id=modern["owner"].id)
                     if ((op.metadata_json or {}).get("turn_lifecycle") or {}).get("version") == TURN_LIFECYCLE_VERSION]
    assert legacy_claims == []
    assert sum(int(e.credits_charged or 0) for e in db.session.query(UsageEvent).filter_by(
        user_id=modern["owner"].id)) == 0


def test_f2_a_modern_reply_that_cannot_be_saved_is_not_charged(client, db, modern, monkeypatch):
    from app.routes import ai_agent
    _script(monkeypatch)
    real = ai_agent._save_turn_project
    def save(uid, sessions, **kwargs):
        history = sessions[modern["thread"]]["chat_history"]
        if any(message.get("content") == REPLY for message in history):
            return False
        return real(uid, sessions, **kwargs)

    monkeypatch.setattr(ai_agent, "_save_turn_project", save)
    before, _held = _spendable(db.session, modern["account"])
    response = client.post(CONTINUE_URL, headers=modern["headers"],
                           json={"thread_id": modern["thread"], "message": "Should we bid?"})
    assert response.status_code >= 400
    after, held = _spendable(db.session, modern["account"])
    assert (after, held) == (before, 0)
    assert REPLY not in _history(db.session, modern["thread"])


def test_f4_a_rollback_inside_a_successful_modern_turn_keeps_its_charge(client, db, modern, monkeypatch):
    _script(monkeypatch, during=lambda: _db.session.rollback())
    before, _held = _spendable(db.session, modern["account"])
    response = client.post(CONTINUE_URL, headers=modern["headers"],
                           json={"thread_id": modern["thread"], "message": "Should we bid?"})
    assert response.status_code == 200, response.get_json()
    after, held = _spendable(db.session, modern["account"])
    assert (before - after, held) == (CHARGE, 0)


def test_f4_a_failed_modern_turn_after_a_rollback_adds_no_credits(client, db, modern, monkeypatch):
    _script(monkeypatch, during=lambda: _db.session.rollback(), fail_with=RuntimeError("provider exploded"))
    before, _held = _spendable(db.session, modern["account"])
    response = client.post(CONTINUE_URL, headers=modern["headers"],
                           json={"thread_id": modern["thread"], "message": "Should we bid?"})
    assert response.status_code >= 400
    after, held = _spendable(db.session, modern["account"])
    assert (after, held) == (before, 0)


def test_f3_a_dropped_modern_stream_is_saved_and_settled_once(client, db, modern, monkeypatch):
    _script(monkeypatch)
    before, _held = _spendable(db.session, modern["account"])
    response = client.post(f"{CONTINUE_URL}?stream=1", headers=modern["headers"],
                           json={"thread_id": modern["thread"], "message": "Should we bid?"}, buffered=False)
    assert response.status_code == 200
    next(iter(response.response), None)  # read at most one event, then the browser goes away
    response.close()
    _wait_idle(db.session)
    after, held = _spendable(db.session, modern["account"])
    assert (before - after, held) == (CHARGE, 0)
    [operation] = _operations(db.session, modern["org"])
    assert (operation.state, operation.delivery_status) == ("finalized", "delivered")
    assert REPLY in _history(db.session, modern["thread"])


def test_a_modern_stream_delivers_the_text_and_the_final_payload(client, db, modern, monkeypatch):
    import json
    _script(monkeypatch)
    response = client.post(f"{CONTINUE_URL}?stream=1", headers=modern["headers"],
                           json={"thread_id": modern["thread"], "message": "Should we bid?"})
    events = [json.loads(line[6:]) for line in response.get_data(as_text=True).splitlines()
              if line.startswith("data: ")]
    assert "".join(e.get("text", "") for e in events if e.get("type") == "delta") == REPLY
    assert events[-1]["type"] == "done" and events[-1]["reply"] == REPLY


def test_a_modern_governed_operation_settles_through_phase12(app, db, modern):
    from app.ai_runtime import execute_customer_operation
    before, _held = _spendable(db.session, modern["account"])
    user = db.session.get(User, modern["owner"].id)

    def generate():
        _provider_reply()
        return {"score": 72}, {"input_tokens": 11, "output_tokens": 7}

    with app.test_request_context():
        value, _usage, settlement = execute_customer_operation(
            user, generate=generate, operation_type="score_next", request_payload={"q": 1}, max_tokens=500,
            thread_id=modern["thread"])
    assert value == {"score": 72} and settlement["charged_credits"] == CHARGE
    after, held = _spendable(db.session, modern["account"])
    assert (before - after, held) == (CHARGE, 0)


def test_a_legacy_organization_beside_a_modern_one_keeps_legacy_charging(client, db, modern, monkeypatch):
    from tests.journeys.test_conversation_turn_lifecycle import _script_generation
    _script_generation(monkeypatch)
    session = db.session
    legacy = User(email=f"legacy-{uuid.uuid4().hex[:8]}@example.invalid", name="Legacy",
                  password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
                  subscription_plan="free", credits_remaining=1_000_000, seat_limit=1, max_seats=1)
    session.add(legacy)
    session.commit()
    from flask_jwt_extended import create_access_token
    headers = {"Authorization": f"Bearer {create_access_token(identity=str(legacy.id))}"}
    from app.routes.sessions import save_user_sessions
    assert save_user_sessions(legacy.id, {"t-legacy": {"session_id": "t-legacy", "user_id": legacy.id,
                                                       "name": "P", "status": "in_progress", "chat_history": []}})
    response = client.post(CONTINUE_URL, headers=headers, json={"thread_id": "t-legacy", "message": "Hi"})
    assert response.status_code == 200
    assert not session.query(AIBillingOperation).filter(AIBillingOperation.actor_user_id == legacy.id).count()


def test_overlapping_modern_turn_requests_replay_one_saved_charge(app, db, modern, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event

    from app import billing_runtime_ai

    generating, duplicate, release = Event(), Event(), Event()

    def pause():
        generating.set()
        assert release.wait(10)

    _script(monkeypatch, during=pause)
    lookup = billing_runtime_ai._find_replay

    def track_replay(*args, **kwargs):
        operation_id = lookup(*args, **kwargs)
        if operation_id is not None:
            duplicate.set()
        return operation_id

    monkeypatch.setattr(billing_runtime_ai, "_find_replay", track_replay)
    headers = {**modern["headers"], "X-Jaspen-Idempotency-Key": "one-turn"}
    data = {"thread_id": modern["thread"], "message": "Should we bid?"}
    before, _held = _spendable(db.session, modern["account"])

    def post(payload):
        with app.test_client() as browser:
            response = browser.post(CONTINUE_URL, headers=headers, json=payload)
            return response.status_code, response.get_json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(post, data)
        try:
            assert generating.wait(10)
            second = pool.submit(post, data)
            assert duplicate.wait(10)
        finally:
            release.set()
        first_status, first_payload = first.result(timeout=10)
        second_status, second_payload = second.result(timeout=10)

    assert first_status == second_status == 200
    assert second_payload["idempotent_replay"] is True
    assert first_payload["credits"] == second_payload["credits"]
    assert second_payload["reply"] == REPLY
    assert post({**data, "message": "Different input"})[0] == 409
    after, held = _spendable(db.session, modern["account"])
    assert (before - after, held) == (CHARGE, 0)
    assert _history(db.session, modern["thread"]).count(REPLY) == 1


def test_a_governed_replay_checks_the_request_fingerprint(app, db, modern):
    from app.ai_runtime import execute_customer_operation
    from app.billing_runtime_ai import ModernOperationRefused

    before, _held = _spendable(db.session, modern["account"])
    user = db.session.get(User, modern["owner"].id)

    def generate():
        _provider_reply()
        return {"score": 72}, {"input_tokens": 11, "output_tokens": 7}

    def call(payload):
        return execute_customer_operation(
            user, generate=generate, operation_type="score_next", request_payload=payload, max_tokens=500,
            thread_id=modern["thread"], idempotency_key="one-governed-operation",
        )

    with app.test_request_context():
        first, _, first_settlement = call({"q": 1})
        replay, _, replay_settlement = call({"q": 1})
        with pytest.raises(ModernOperationRefused, match="idempotency_conflict"):
            call({"q": 2})

    assert replay == first
    assert replay_settlement["idempotent_replay"] is True
    assert first_settlement["charged_credits"] == replay_settlement["charged_credits"] == CHARGE
    assert _spendable(db.session, modern["account"]) == (before - CHARGE, 0)


def test_failed_delivery_envelope_rolls_back_a_new_reply_and_its_audit_event(client, db, modern, monkeypatch):
    from app import billing_reliable_delivery as delivery
    from app.models import AdminAuditEvent

    _script(monkeypatch)
    before, _held = _spendable(db.session, modern["account"])
    thread_id = f"t-{uuid.uuid4().hex[:8]}"

    def fail_envelope(*args, **kwargs):
        raise RuntimeError("delivery envelope write failed")

    monkeypatch.setattr(delivery, "persist_successful_response", fail_envelope)
    response = client.post(
        "/api/v1/ai-agent/conversation/start", headers=modern["headers"],
        json={"thread_id": thread_id, "message": "Should we bid?"},
    )
    assert response.status_code >= 400
    assert _spendable(db.session, modern["account"]) == (before, 0)
    assert REPLY not in _history(db.session, thread_id)
    events = db.session.query(AdminAuditEvent).filter_by(action="session.created").all()
    assert all(event.details.get("thread_id") != thread_id for event in events)


def test_modern_batch_uses_one_phase12_settlement_after_artifact_processing(app, db, modern, monkeypatch):
    from app.ai_runtime import (
        execute_customer_operation, finalize_batch_charge_allocation, reverse_customer_operation_charge,
    )
    from app.models import AIOperation
    from app.routes import ai_agent

    def legacy_release(*args, **kwargs):
        raise AssertionError("a modern charge reached the legacy credit meter")

    monkeypatch.setattr(ai_agent, "_release_reserved_credits", legacy_release)
    before, _held = _spendable(db.session, modern["account"])
    user = db.session.get(User, modern["owner"].id)

    def generate():
        _provider_reply()
        return {"results": [{"name": "Option A"}, {"name": "Option B"}]}, {"input_tokens": 11, "output_tokens": 7}

    with app.test_request_context():
        _, _, settlement = execute_customer_operation(
            user, generate=generate, operation_type="score_batch", request_payload={"batch": 1},
            max_tokens=500, thread_id=modern["thread"],
        )
        operation = db.session.get(AIOperation, settlement["operation_id"])
        envelope = operation.result_json
        assert reverse_customer_operation_charge(user, settlement, error_code="later_workflow_failure") == 0
        assert finalize_batch_charge_allocation(
            user, settlement, component_ids=["a", "b"], persisted_component_ids=["a"],
        ) == {"charged_credits": CHARGE, "allocations": []}
        assert operation.result_json == envelope
    assert _spendable(db.session, modern["account"]) == (before - CHARGE, 0)


def test_decision_kit_provider_call_runs_under_the_modern_reservation(client, db, modern, monkeypatch):
    from app.models_billing_phase12 import AIProviderCallUsage
    from app.routes import ai_agent

    _script(monkeypatch)

    def classify(*args, **kwargs):
        _provider_reply()
        return {"kit": "none", "confidence": "high", "evidence_quote": ""}

    monkeypatch.setattr(ai_agent, "_classify_decision_kit", classify)
    response = client.post(
        "/api/v1/ai-agent/conversation/start", headers=modern["headers"],
        json={"thread_id": f"t-{uuid.uuid4().hex[:8]}", "message": "Should we bid?"},
    )
    assert response.status_code == 200
    [operation] = _operations(db.session, modern["org"])
    calls = db.session.query(AIProviderCallUsage).filter_by(operation_id=operation.operation_id).all()
    assert len(calls) == 2
    assert {call.attempt_number for call in calls} == {operation.delivered_attempt_number}


def test_governed_generation_failure_absorbs_reported_usage_and_keeps_the_fallback(app, db, modern):
    from app.ai_runtime import execute_customer_operation
    from app.models_billing_phase12 import AIAbsorbedUsage

    before, _held = _spendable(db.session, modern["account"])
    user = db.session.get(User, modern["owner"].id)

    def generate():
        _provider_reply()  # transport success is not a delivered plan
        return {"provider_success": False, "provider_error": "invalid_lineage"}, {"generation_failed": True}

    with app.test_request_context():
        value, usage, settlement = execute_customer_operation(
            user, generate=generate, operation_type="execution_plan", request_payload={"q": 1},
            max_tokens=500, thread_id=modern["thread"],
        )
    assert value["provider_success"] is False and usage["generation_failed"] is True
    assert settlement["delivery_status"] == "undelivered" and settlement["charged_credits"] == 0
    absorbed = db.session.query(AIAbsorbedUsage).filter_by(operation_id=settlement["operation_id"]).one()
    assert absorbed.absorbed_credits == CHARGE
    assert _spendable(db.session, modern["account"]) == (before, 0)


def test_ai_family_can_deliver_before_public_readers_are_enabled(client, db, modern, monkeypatch):
    monkeypatch.setenv(bc.SETTING, ALL.rsplit(",", 1)[0])
    _script(monkeypatch)
    before, _held = _spendable(db.session, modern["account"])
    response = client.post(
        CONTINUE_URL, headers=modern["headers"],
        json={"thread_id": modern["thread"], "message": "Should we bid?"},
    )
    assert response.status_code == 200
    assert response.get_json()["reply"] == REPLY
    assert _spendable(db.session, modern["account"]) == (before - CHARGE, 0)


def test_a_modern_scoring_failure_keeps_the_existing_retry_card_without_a_charge(client, db, modern, monkeypatch):
    from app.models_billing_phase12 import AIAbsorbedUsage
    from app.routes import ai_agent

    _script(monkeypatch)

    def fail_scoring(*args, **kwargs):
        reply, usage, _actions, mutations, undo = _provider_reply()
        actions = [{"tool": "generate_scorecard", "result": {
            "ok": False, "failure_state": True, "error": "The scoring step failed.", "code": "scoring_failed",
        }}]
        return reply, usage, actions, mutations, undo

    monkeypatch.setattr(ai_agent, "_generate_assistant_reply", fail_scoring)
    before, _held = _spendable(db.session, modern["account"])
    headers = {**modern["headers"], "X-Jaspen-Idempotency-Key": "score-failed"}
    payload = {"thread_id": modern["thread"], "message": "Should we bid?"}
    response = client.post(CONTINUE_URL, headers=headers, json=payload)
    assert response.status_code == 200
    body = response.get_json()
    assert body["retryable"] is True and body["failure_state"] is True and body["reply"] == ""
    assert body["artifact_messages"]
    [operation] = _operations(db.session, modern["org"])
    assert operation.delivery_status == "undelivered" and operation.charged_credits == 0
    absorbed = db.session.query(AIAbsorbedUsage).filter_by(operation_id=operation.operation_id).one()
    assert absorbed.absorbed_credits == CHARGE
    assert _spendable(db.session, modern["account"]) == (before, 0)
    replay = client.post(CONTINUE_URL, headers=headers, json=payload)
    assert replay.status_code == 200 and replay.get_json()["idempotent_replay"] is True


@pytest.mark.parametrize("save_fails", [False, True])
def test_modern_plan_settles_only_if_its_existing_delivery_path_succeeds(client, db, modern, monkeypatch, save_fails):
    import json

    from app.routes import strategy
    from tests.test_plan_build_jobs import _ai_plan, _seed

    _seed(modern["owner"], db, modern["thread"])
    monkeypatch.setattr(strategy, "get_llm_client", lambda: object())

    def provider(*args, **kwargs):
        _reply, usage, _actions, _mutations, _undo = _provider_reply()
        return json.dumps(_ai_plan()), usage

    monkeypatch.setattr(strategy, "_strategy_generate_reply", provider)
    if save_fails:
        def reject_save(*args, **kwargs):
            raise RuntimeError("plan store unavailable")

        monkeypatch.setattr(strategy, "_persist_generated_plan", reject_save)

    before, _held = _spendable(db.session, modern["account"])
    response = client.post(
        f"/api/v1/strategy/threads/{modern['thread']}/ai-wbs", headers=modern["headers"],
        json={"commit": True, "scorecard_id": "planner-card"},
    )
    [operation] = _operations(db.session, modern["org"])
    assert operation.delivery_status == ("undelivered" if save_fails else "delivered")
    assert _spendable(db.session, modern["account"]) == (before if save_fails else before - CHARGE, 0)
    if save_fails:
        assert response.status_code == 500
    else:
        assert response.status_code == 200 and len(response.get_json()["project_wbs"]["tasks"]) == 12


def test_modern_batch_records_one_ordered_provider_attempt(app, db, modern, monkeypatch):
    from threading import get_ident

    from app.ai_runtime import execute_customer_operation
    from app.models_billing_phase12 import AIProviderCallUsage
    from app.routes import strategy

    threads = []

    def score(*args, **kwargs):
        threads.append(get_ident())
        _, usage, *_ = _provider_reply()
        return {"jaspen_score": 72, "name": kwargs["option_name"]}, usage

    monkeypatch.setattr(strategy, "_generate_jaspen_scorecard", score)
    ideas = [{"name": name, "description": name} for name in ("Option A", "Option B", "Option C")]
    before, _held = _spendable(db.session, modern["account"])
    user = db.session.get(User, modern["owner"].id)

    def generate():
        cards, summary, usage = strategy._generate_batch_scorecards(object(), ideas, return_usage=True)
        return {"cards": cards, "summary": summary}, usage

    with app.test_request_context():
        result, _, settlement = execute_customer_operation(
            user, generate=generate, operation_type="score_batch", request_payload={"ideas": ideas},
            max_tokens=500, thread_id=modern["thread"],
        )
    assert len(result["cards"]) == 3 and len(threads) == 3 and len(set(threads)) == 1
    calls = db.session.query(AIProviderCallUsage).filter_by(operation_id=settlement["operation_id"]).all()
    assert sorted((call.attempt_number, call.call_index) for call in calls) == [(1, 0), (1, 1), (1, 2)]
    assert _spendable(db.session, modern["account"]) == (before - 994, 0)


def test_modern_cache_only_operation_returns_results_and_releases_the_hold(app, db, modern):
    from app.ai_runtime import execute_customer_operation

    before, _held = _spendable(db.session, modern["account"])
    user = db.session.get(User, modern["owner"].id)
    with app.test_request_context():
        value, usage, settlement = execute_customer_operation(
            user, generate=lambda: ({"score": 72}, {"provider": "canonical_cache"}),
            operation_type="score_batch", request_payload={"q": 1}, max_tokens=500, thread_id=modern["thread"],
        )
    assert value == {"score": 72} and usage == {"provider": "canonical_cache"}
    assert settlement["charged_credits"] == 0 and settlement["delivery_status"] == "no_billable_usage"
    assert _spendable(db.session, modern["account"]) == (before, 0)


@pytest.mark.parametrize("keep_generated, reuse_second", [(True, False), (False, False), (False, True)])
def test_modern_score_batch_settles_the_operation_only_if_it_delivers_a_result(
    client, db, modern, monkeypatch, keep_generated, reuse_second,
):
    from app.routes import strategy

    def generate(*args, **kwargs):
        _, usage, *_ = _provider_reply()
        return [{"jaspen_score": 72}, {"jaspen_score": 73, "reused_stored_result": reuse_second}], {}, usage

    save = strategy.upsert_scorecard

    def accept_first_only(*args, **kwargs):
        name = kwargs["payload"]["name"]
        if (keep_generated and name == "Option A") or (reuse_second and name == "Option B"):
            return save(*args, **kwargs)
        raise RuntimeError("scorecard store unavailable")

    monkeypatch.setattr(strategy, "_generate_batch_scorecards", generate)
    monkeypatch.setattr(strategy, "upsert_scorecard", accept_first_only)
    monkeypatch.setattr(strategy, "get_llm_client", lambda: object())
    before, _held = _spendable(db.session, modern["account"])
    response = client.post(
        f"/api/v1/strategy/threads/{modern['thread']}/score-batch", headers=modern["headers"],
        json={"ideas": [{"name": "Option A"}, {"name": "Option B"}]},
    )
    assert response.status_code == 200
    result = response.get_json()
    assert result["persisted_project_count"] == int(keep_generated or reuse_second)
    assert len(result["not_persisted_project_names"]) == (1 if keep_generated or reuse_second else 2)
    [operation] = _operations(db.session, modern["org"])
    assert operation.delivery_status == ("delivered" if keep_generated else "undelivered")
    assert _spendable(db.session, modern["account"]) == (before - CHARGE if keep_generated else before, 0)


@pytest.mark.parametrize("save_fails", [False, True])
def test_modern_analyze_settles_only_a_retained_scorecard(client, db, modern, monkeypatch, save_fails):
    from app.models import Scorecard
    from app.routes import strategy

    def generate(*args, **kwargs):
        _, usage, *_ = _provider_reply()
        return {"jaspen_score": 72}, usage

    monkeypatch.setattr(strategy, "get_llm_client", lambda: object())
    monkeypatch.setattr(strategy, "_generate_jaspen_scorecard", generate)
    if save_fails:
        def reject_save(*args, **kwargs):
            raise RuntimeError("scorecard store unavailable")

        monkeypatch.setattr(strategy, "upsert_scorecard", reject_save)

    before, _ = _spendable(db.session, modern["account"])
    response = client.post(
        "/api/v1/strategy/analyze", headers=modern["headers"],
        json={"description": "Evaluate a supplier contract"},
    )
    [operation] = _operations(db.session, modern["org"])
    expected_remaining = before if save_fails else before - CHARGE
    assert _spendable(db.session, modern["account"]) == (expected_remaining, 0)
    if save_fails:
        assert response.status_code == 500
        assert response.get_json()["code"] == "scorecard_persistence_failed"
        assert operation.delivery_status == "undelivered"
        assert db.session.query(Scorecard).count() == 0
    else:
        assert response.status_code == 200
        analysis = response.get_json()["analysis"]
        assert analysis["meta"]["credits_remaining"] == expected_remaining
        assert operation.delivery_status == "delivered"
        scorecard = db.session.get(Scorecard, analysis["id"])
        assert scorecard.organization_id == modern["org"].id
        assert scorecard.thread_id == analysis["thread_id"]
