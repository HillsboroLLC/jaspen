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
