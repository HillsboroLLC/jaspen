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
    monkeypatch.setattr(ai_agent, "_save_turn_project", lambda uid, sessions, **k: (
        False if k.get("commit") is False else real(uid, sessions, **k)))
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
