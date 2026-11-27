"""I4: the ai_reservation family runtime. Modern AI operations run through Phase 12.

An AI operation's context is the organization whose work it is (D4, and the I1
dispatch contract): a chat turn's project organization, else the member's context
organization. ``billing_cutover.modern_context(family="ai_reservation", ...)``
decides the handler:

* ``None``: a legacy organization; the legacy credit path answers, unchanged
  (OD-1 Option C);
* a ``ModernContext``: this module answers;
* ``BillingFamilyDisabledError``: a modern organization with the family off;
  nobody answers, and the operation is refused before any provider call.

A modern operation is one ``AIOperation`` row (claim version
``MODERN_TURN_LIFECYCLE_VERSION``, D-2) that Phase 12 authorizes for the
organization's billing account and the reliable-delivery worker (I3) runs:
heartbeat, persist-then-settle, and recovery. Every provider request the
operation's generation makes is reported to Phase 12 through the provider call
observer (``Phase12CallRecorder``): checked before it is sent and recorded after
it ends. Nothing here charges in a request transaction, so a rollback inside
generation cannot add or lose credits (F4), an unsaved reply is never charged
(F2), and a dropped connection neither strands nor charges a reservation (F3).
"""

import math
import uuid
from datetime import datetime, timezone

from .ai_audit import MODERN_TURN_LIFECYCLE_VERSION
from .models import AIOperation


ROUTER_VERSION = "jaspen.ai.modern.v1"
POLICY_VERSION = "phase12"
CHARS_PER_TOKEN_BOUND = 2  # a conservative input bound: real prompts run near four characters per token


class ModernOperationRefused(RuntimeError):
    """A modern operation could not start; ``code`` is operational, never customer wording."""

    def __init__(self, code, detail=None):
        super().__init__(detail or code)
        self.code = code


def input_token_bound(input_characters):
    """A deterministic upper bound on a request's input tokens from its prompt characters."""
    return max(1, math.ceil(int(input_characters or 0) / CHARS_PER_TOKEN_BOUND))


def claim_modern_operation(session, *, user_id, organization_id, operation_type, thread_id=None, route=None,
                           streaming=None, idempotency_key=None, request_fingerprint=None, prompt_family=None):
    """The durable ``AIOperation`` a modern operation is authorized and delivered under. The caller commits."""
    lifecycle = {
        "version": MODERN_TURN_LIFECYCLE_VERSION, "route": route, "streaming": streaming,
        "claimed_at": datetime.now(timezone.utc).isoformat(), "prompt_family": prompt_family,
    }
    operation = AIOperation(
        id=str(uuid.uuid4()), user_id=str(user_id), organization_id=str(organization_id),
        operation_type=str(operation_type), status="started", thread_id=thread_id,
        router_version=ROUTER_VERSION, policy_version=POLICY_VERSION,
        idempotency_key=idempotency_key, request_fingerprint=request_fingerprint,
        metadata_json={"turn_lifecycle": lifecycle},
    )
    session.add(operation)
    session.flush()
    return operation


class Phase12CallRecorder:
    """A provider call observer that reports one operation's requests to its delivery context.

    ``ctx`` is the worker's ``DeliveryContext``: ``begin_attempt()``,
    ``check_call(...)``, ``record_call(...)`` and ``now()``. The first request
    opens attempt 1. A request after a failed one (a fallback candidate or a
    retry) opens a new attempt; a request after a successful one is the next
    tool iteration of the same attempt. ``delivered_attempt`` is the attempt of
    the last successful request.
    """

    def __init__(self, ctx):
        self._ctx = ctx
        self._attempt = None
        self._call_index = 0
        self._component = "primary"
        self._new_attempt = False
        self.delivered_attempt = None

    def before_call(self, provider, model, request):
        if self._attempt is None or self._new_attempt:
            component = "primary" if self._attempt is None else "fallback"
            self._attempt, self._call_index, self._new_attempt = self._ctx.begin_attempt(), 0, False
        else:
            self._call_index += 1
            component = "tool_iteration"
        max_input = input_token_bound(request.get("input_characters"))
        max_output = max(1, int(request.get("max_output_tokens") or 1))
        self._ctx.check_call(attempt_number=self._attempt, call_index=self._call_index, provider=provider,
                             model=model, max_input_tokens=max_input, max_output_tokens=max_output)
        return {"attempt": self._attempt, "call_index": self._call_index, "component": component,
                "provider": provider, "model": model, "requested_at": self._ctx.now()}

    def after_call(self, handle, outcome, *, input_tokens, output_tokens, error=None, status_code=None,
                   request_id=None):
        reported = input_tokens is not None and output_tokens is not None
        mapped = {"succeeded": "succeeded", "abandoned": "cancelled"}.get(outcome)
        if mapped is None:
            mapped = "timeout" if "timeout" in type(error).__name__.lower() else "failed"
        self._ctx.record_call(
            attempt_number=handle["attempt"], call_index=handle["call_index"], component=handle["component"],
            provider=handle["provider"], model=handle["model"], outcome=mapped,
            usage_label="reported" if reported else "unknown",
            input_tokens=int(input_tokens) if reported else None,
            output_tokens=int(output_tokens) if reported else None,
            requested_at=handle["requested_at"], finished_at=self._ctx.now(),
            error_category=None if mapped == "succeeded" else (type(error).__name__ if error else mapped),
            provider_request_id=request_id,
        )
        if mapped == "succeeded":
            self.delivered_attempt = handle["attempt"]
        else:
            self._new_attempt = True
