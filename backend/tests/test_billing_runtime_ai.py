"""I4: the ai_reservation family runtime."""

from datetime import datetime, timedelta

import pytest

from app import ai_audit
from app import billing_runtime_ai as rt
from app.ai_providers import anthropic as anthropic_provider
from app.ai_providers import observer
from tests.test_ai_provider_observer import KW, FakeClient
from tests.test_billing_cutover import _org, _user


class FakeContext:
    """The worker's DeliveryContext surface the recorder uses."""

    def __init__(self, refuse_at=None):
        self.attempts, self.checks, self.records, self.refuse_at = 0, [], [], refuse_at

    def begin_attempt(self):
        self.attempts += 1
        return self.attempts

    def check_call(self, **kwargs):
        if self.refuse_at is not None and len(self.checks) == self.refuse_at:
            raise RuntimeError("runaway bound reached")
        self.checks.append(kwargs)

    def record_call(self, **kwargs):
        self.records.append(kwargs)

    def now(self):
        return datetime(2026, 11, 26, 12, 0)


def test_the_recorder_checks_before_and_records_after_every_request():
    ctx = FakeContext()
    recorder = rt.Phase12CallRecorder(ctx)
    with observer.observing(recorder):
        anthropic_provider.message_create(FakeClient(failures={"m1"}), candidates=["m1", "m2"], **KW)  # fallback
        anthropic_provider.message_create(FakeClient(), candidates=["m2"], **KW)  # the next tool round
    assert [(c["attempt_number"], c["call_index"], c["model"]) for c in ctx.checks] == [
        (1, 0, "m1"), (2, 0, "m2"), (2, 1, "m2")]
    assert [(r["component"], r["outcome"], r["usage_label"], r["input_tokens"]) for r in ctx.records] == [
        ("primary", "failed", "unknown", None), ("fallback", "succeeded", "reported", 11),
        ("tool_iteration", "succeeded", "reported", 11)]
    assert ctx.records[0]["error_category"] == "RuntimeError" and ctx.records[1]["error_category"] is None
    assert recorder.delivered_attempt == 2
    assert all(c["max_input_tokens"] >= rt.input_token_bound(1) and c["max_output_tokens"] == 500
               for c in ctx.checks)


def test_a_refused_check_sends_nothing_and_records_nothing():
    ctx, client = FakeContext(refuse_at=0), FakeClient()
    with observer.observing(rt.Phase12CallRecorder(ctx)), pytest.raises(RuntimeError, match="runaway"):
        anthropic_provider.message_create(client, candidates=["m1"], **KW)
    assert client.sent == [] and ctx.records == []


def test_the_input_bound_is_conservative_and_deterministic():
    assert rt.input_token_bound(0) == 1
    assert rt.input_token_bound(4000) == 2000  # four characters per token in practice: twice the real count


def test_a_modern_claim_is_never_stale_p4_0_evidence(db):
    """D-2: whatever its age, a Phase 12 operation stays in flight for the X1 classifier."""
    session = db.session
    owner = _user(session)
    org = _org(session, owner)
    operation = rt.claim_modern_operation(session, user_id=owner.id, organization_id=org.id,
                                          operation_type="conversation", thread_id="t1", route="continue",
                                          streaming=False)
    lifecycle = operation.metadata_json["turn_lifecycle"]
    assert lifecycle["version"] == ai_audit.MODERN_TURN_LIFECYCLE_VERSION != ai_audit.TURN_LIFECYCLE_VERSION
    later = datetime.utcnow() + timedelta(days=30)
    result = ai_audit.classify_unclosed_operation(operation, now=later, max_turn_seconds=60)
    assert (result["class"], result["in_flight"], result["reason"]) == (
        ai_audit.UNCLOSED_OUTSTANDING, True, "phase12_operation")
    session.rollback()


@pytest.mark.parametrize(("runaway_seconds", "wait_seconds"), [(150, 165), (600, 165), (30, 45)])
def test_modern_operation_wait_stays_below_staging_request_timeout(runaway_seconds, wait_seconds):
    from unittest.mock import Mock

    session = Mock()
    session.execute.return_value.scalar_one_or_none.return_value = {
        "runaway": {"max_operation_seconds": runaway_seconds}
    }
    assert rt.operation_timeout_seconds(session) == wait_seconds


def test_an_unsaved_request_does_not_leave_a_keyed_claim(db):
    from app.billing_cutover import ModernContext
    from app.models import AIOperation

    session = db.session
    owner = _user(session)
    org = _org(session, owner)
    session.commit()

    def reject_request():
        raise rt.ModernOperationRefused("conversation_persist_failed")

    with pytest.raises(rt.ModernOperationRefused, match="conversation_persist_failed"):
        rt.submit_modern_operation(
            session, context=ModernContext(org.id, "unused"), user_id=owner.id, operation_type="conversation",
            generate=None, max_output_tokens=500, config={}, provider_timeout_seconds=60,
            idempotency_key="unsaved-request", request_fingerprint="original", before_authorize=reject_request,
        )
    session.rollback()
    assert session.query(AIOperation).filter_by(idempotency_key="unsaved-request").count() == 0


def test_work_organization_uses_the_callers_canonical_project(db):
    from app.models import UserSession

    session = db.session
    actor = _user(session)
    other = _user(session)
    work_org = _org(session, actor)
    unrelated = _org(session, other)
    actor.active_organization_id = work_org.id
    session.add_all([
        UserSession(user_id=actor.id, organization_id=work_org.id, session_id="duplicate", payload={}),
        UserSession(user_id=other.id, organization_id=unrelated.id, session_id="duplicate", payload={}),
        UserSession(user_id=other.id, organization_id=unrelated.id, session_id="unrelated", payload={}),
    ])
    session.commit()

    assert rt.operation_organization_id(session, actor, "duplicate") == work_org.id
    assert rt.operation_organization_id(session, actor, "unrelated") == work_org.id

    from app.session_access import worker_organization_scope

    with worker_organization_scope(other.id, work_org.id):
        # A worker keeps the organization it obtained before running, even if
        # the same actor's active organization and same-id project differ.
        assert rt.operation_organization_id(session, other, "duplicate") == work_org.id
    assert rt.operation_organization_id(session, other, "duplicate") == unrelated.id
