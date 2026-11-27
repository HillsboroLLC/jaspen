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
# Keep request polling below the approved 180-second staging request timeout.
MAX_STAGING_WAIT_SECONDS = 165
SETTLEMENT_MARGIN_SECONDS = 15


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
        self.current_attempt = None
        self._call_index = 0
        self._component = "primary"
        self._new_attempt = False
        self.delivered_attempt = None

    def before_call(self, provider, model, request):
        if self._attempt is None or self._new_attempt:
            component = "primary" if self._attempt is None else "fallback"
            self._attempt, self._call_index, self._new_attempt = self._ctx.begin_attempt(), 0, False
            self.current_attempt = self._attempt
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


# ---------------------------------------------------------------------------
# Running a modern operation through Phase 12 and the reliable-delivery worker
# ---------------------------------------------------------------------------

# The first hold's token assumption. It is not a cap: every call is still checked against the policy's per-call
# bounds, and settlement holds more, up to the reservation ceiling and what the account can spend (Phase 12).
# Kept small so a Free organization's allowance can start an ordinary turn.
INITIAL_INPUT_BOUND = 2000
INITIAL_OUTPUT_BOUND = 1000
EXECUTOR_NAME = "in_process"
_REGISTRY = {}  # operation id -> _Pending, for the process that submitted it


class _Pending:
    __slots__ = ("generate", "on_persist", "result", "failure")

    def __init__(self, generate, on_persist):
        self.generate, self.on_persist, self.result, self.failure = generate, on_persist, None, None


def _worker():
    from . import billing_delivery_worker as worker

    if EXECUTOR_NAME not in getattr(worker, "_EXECUTORS", {}):
        worker.executor(EXECUTOR_NAME)(_run_registered)
    return worker


def configured_candidates(session, config):
    """The deployment's configured models that the effective pricing version prices, as (provider, model).

    A generation that calls any other model is refused before the call (Phase 12
    ``UnpricedModelError``), so the operation fails closed with no charge.
    """
    from sqlalchemy import select

    from .ai_governance import resolve_anthropic_model
    from .models import PricingPolicyVersion, ProviderRateEntry

    models = config.get("LLM_PROVIDER_MODELS") if isinstance(config.get("LLM_PROVIDER_MODELS"), dict) else {}
    wanted = set()
    for key in ("claude_haiku", "claude_sonnet", "claude_opus"):
        wanted.add(("anthropic", resolve_anthropic_model(models.get(key), model_key=key)))
    for key in ("gemini_flash", "gemini_pro"):
        if models.get(key):
            wanted.add(("google", str(models[key]).strip()))
    priced = set(session.execute(
        select(ProviderRateEntry.provider, ProviderRateEntry.model)
        .join(PricingPolicyVersion, PricingPolicyVersion.id == ProviderRateEntry.pricing_policy_version_id)
        .where(PricingPolicyVersion.state == "effective")
    ).all())
    candidates = sorted(wanted & {tuple(row) for row in priced})
    if not candidates:
        raise ModernOperationRefused("pricing_required", "no configured model is priced by the effective policy")
    return candidates


def _run_registered(ctx):
    """The worker executor: run the submitting process's in-memory generation under the call recorder."""
    from .ai_providers import observer as provider_observer

    worker = _worker()
    pending = _REGISTRY.pop(ctx.operation_id, None)  # the submitting caller keeps its own reference
    if pending is None:
        raise worker.DeliveryFailed("not_resumable")  # another process or a restart: closed undelivered, no charge
    recorder = Phase12CallRecorder(ctx)

    def emit(text):
        if recorder.current_attempt is not None and text:
            ctx.emit(recorder.current_attempt, text)

    from .routes.ai_agent import ai_customer_scope

    try:
        # No signed-in request carries the customer on the worker thread; the scope does (as for plan builds).
        with provider_observer.observing(recorder), ai_customer_scope(ctx.actor_user_id):
            value, usage = pending.generate(emit=emit, should_stop=ctx.should_stop)
    except Exception as exc:  # the generation's own failure: no usable response
        pending.failure = exc
        raise worker.DeliveryFailed(type(exc).__name__) from exc
    if recorder.delivered_attempt is None:
        return worker.NoBillableUsage()
    pending.result = (value, usage)
    return worker.DeliveryResult(delivered_attempt_number=recorder.delivered_attempt,
                                 response={"value": value, "usage": usage}, on_persist=pending.on_persist)


def submit_modern_operation(session, *, context, user_id, operation_type, generate, max_output_tokens,
                            config, provider_timeout_seconds, thread_id=None, route=None, streaming=None,
                            idempotency_key=None, request_fingerprint=None, prompt_family=None, on_persist=None):
    """Claim, authorize and submit one modern operation; commits. Returns ``(operation_id, pending)``.

    ``generate(emit, should_stop) -> (value, usage)`` runs on the worker thread.
    ``on_persist(session, response)`` runs inside the transaction that saves the
    response. Refusals raise ``ModernOperationRefused`` (``credit_exhausted``,
    ``capacity_denied``, ``pricing_required``) with nothing reserved.
    """
    from .billing_ai_operations import authorize_ai_operation

    worker = _worker()
    operation = claim_modern_operation(
        session, user_id=user_id, organization_id=context.organization_id, operation_type=operation_type,
        thread_id=thread_id, route=route, streaming=streaming, idempotency_key=idempotency_key,
        request_fingerprint=request_fingerprint, prompt_family=prompt_family,
    )
    auth = authorize_ai_operation(
        session, operation_id=operation.id, actor_user_id=str(user_id), step_key=f"{operation_type}:1",
        candidates=[list(pair) for pair in configured_candidates(session, config)],
        max_input_tokens=INITIAL_INPUT_BOUND,
        max_output_tokens=max(1, min(int(max_output_tokens or 1), INITIAL_OUTPUT_BOUND)),
    )
    if auth.outcome != "authorized":
        operation.status, operation.error_code = "failed", auth.outcome
        session.commit()
        raise ModernOperationRefused(auth.outcome)
    try:
        worker.submit_delivery(
            session, operation_id=operation.id, organization_id=context.organization_id,
            actor_user_id=str(user_id), executor=EXECUTOR_NAME,
            payload={"operation_type": operation_type, "thread_id": thread_id, "route": route},
            provider_timeout_seconds=provider_timeout_seconds,
        )
    except worker.DeliveryTimingError:
        worker.release_unsubmitted_operation(session, operation_id=operation.id,
                                             organization_id=context.organization_id, actor_user_id=str(user_id))
        session.commit()
        raise ModernOperationRefused("delivery_timing")
    session.commit()  # the job is durable before any provider call
    pending = _REGISTRY[operation.id] = _Pending(generate, on_persist)
    worker.start_in_process(operation.id)
    return operation.id, pending


def forget(operation_id):
    """Drop an in-memory generation the worker never claimed (for example after a refused submit)."""
    return _REGISTRY.pop(operation_id, None)


# ---------------------------------------------------------------------------
# Waiting for an outcome, and the governed-operation entry point
# ---------------------------------------------------------------------------

POLL_SECONDS = 0.1


def _outcome_session_factory():
    """Independent sessions for watching an operation, so the request's own session is never used by two
    threads at once while the worker thread runs the generation."""
    return _worker().default_session_factory()


def wait_for_outcome(*, operation_id, context, user_id, timeout_seconds, sessions=None):
    """Poll the job until it finished (settled, absorbed or closed). Raises ``delivery_pending`` on timeout."""
    import time

    worker = _worker()
    factory = sessions or _outcome_session_factory()
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    with factory() as watch:
        while True:
            outcome = worker.delivery_outcome(watch, operation_id=operation_id,
                                              organization_id=context.organization_id,
                                              actor_user_id=str(user_id))
            watch.rollback()  # the next poll reads a fresh snapshot
            if outcome["finished"]:
                return outcome
            if time.monotonic() >= deadline:
                raise ModernOperationRefused("delivery_pending")
            time.sleep(POLL_SECONDS)


def operation_timeout_seconds(session):
    """How long a caller waits: the effective capacity policy's execution bound plus a settlement margin."""
    from sqlalchemy import select

    from .models import CapacityPolicyVersion

    rules = session.execute(select(CapacityPolicyVersion.rules_json).where(
        CapacityPolicyVersion.state == "effective")).scalar_one_or_none() or {}
    runaway = rules.get("runaway") if isinstance(rules, dict) else {}
    bound = int((runaway or {}).get("max_operation_seconds") or 0)
    return min(MAX_STAGING_WAIT_SECONDS, bound + SETTLEMENT_MARGIN_SECONDS)


def _jsonable(value):
    import json

    return json.loads(json.dumps(value, default=str))


def execute_modern_operation(user, *, context, generate, operation_type, idempotency_key, request_fingerprint,
                             max_tokens, thread_id=None, validate=None, prompt_family=None):
    """``ai_runtime.execute_customer_operation`` for a modern organization: the same ``(value, usage,
    settlement)`` contract, through Phase 12 and the worker. A failure is never charged and raises the
    generation's own error, as the legacy path does."""
    from flask import current_app

    from . import db
    from .ai_providers import anthropic as anthropic_provider
    from .ai_runtime import AIOperationInProgress

    session = db.session
    if idempotency_key:
        from sqlalchemy import select

        existing = session.execute(select(AIOperation).where(
            AIOperation.idempotency_key == idempotency_key)).scalar_one_or_none()
        if existing is not None:
            identity = dict(operation_id=existing.id, organization_id=context.organization_id,
                            actor_user_id=str(user.id))
            outcome = _worker().delivery_outcome(session, **identity)
            if not outcome["finished"]:
                raise AIOperationInProgress("This request is already being processed.")
            response = _worker().read_delivery(session, include_chunks=False, **identity).response
            if not outcome["persisted"] or not isinstance(response, dict):
                raise ModernOperationRefused(outcome["outcome"] or "not_delivered")
            return response.get("value"), dict(response.get("usage") or {}), _settlement(
                outcome, existing.id, replay=True)

    def run(emit, should_stop):
        value, usage = generate()
        if validate is not None:
            value = validate(value)
        return _jsonable(value), _jsonable(dict(usage or {}))

    operation_id, pending = submit_modern_operation(
        session, context=context, user_id=user.id, operation_type=operation_type, generate=run,
        max_output_tokens=max_tokens, config=current_app.config,
        provider_timeout_seconds=anthropic_provider.request_timeout_seconds(), thread_id=thread_id,
        streaming=False, idempotency_key=idempotency_key, request_fingerprint=request_fingerprint,
        prompt_family=prompt_family,
    )
    try:
        outcome = wait_for_outcome(operation_id=operation_id, context=context, user_id=user.id,
                                   timeout_seconds=operation_timeout_seconds(session))
    finally:
        forget(operation_id)
    session.expire_all()
    if not outcome["persisted"]:
        if pending is not None and pending.failure is not None:
            raise pending.failure
        raise ModernOperationRefused(outcome["outcome"] or "not_delivered")
    value, usage = pending.result if pending is not None and pending.result else (None, {})
    return value, dict(usage or {}), _settlement(outcome, operation_id)


def _settlement(outcome, operation_id, *, replay=False):
    return {
        "charged_credits": int(outcome.get("charged_credits") or 0), "reserved_credits": 0,
        "projected_credits": int(outcome.get("charged_credits") or 0), "provider_cost_usd": None,
        "policy_mode": "phase12", "remaining": None, "customer_visible": True, "idempotent_replay": replay,
        "operation_id": operation_id, "billing_state": outcome.get("billing_state"),
        "delivery_status": outcome.get("delivery_status"),
    }


def operation_organization_id(session, user, thread_id=None):
    """The organization whose work an operation is: the thread's project organization, else the member's
    context organization (D4: the work's organization pays)."""
    from sqlalchemy import select

    from .billing_cutover import context_organization_id
    from .models import UserSession

    if thread_id:
        organizations = {row for row in session.execute(select(UserSession.organization_id).where(
            UserSession.session_id == str(thread_id), UserSession.organization_id.isnot(None))).scalars()}
        if len(organizations) == 1:
            return organizations.pop()
    return context_organization_id(session, getattr(user, "id", None))
