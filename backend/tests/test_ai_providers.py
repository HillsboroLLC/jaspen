"""P5a: provider SDKs live in app/ai_providers, and moving them there changed
nothing a provider receives and nothing Jaspen records about usage.

Two kinds of test sit here (adapter-level tests are in
test_ai_provider_adapters.py):

1. A capture harness. Every case drives real Jaspen code (the governed router,
   the conversation route, the tool loop, streaming, decision capture) against
   the real Anthropic SDK, whose HTTP transport is replaced in-process, and
   against a recorded Gemini HTTP layer. Each request is kept as the exact
   bytes that would have gone over the wire. Each case also keeps its
   credit-relevant results: the usage the code returned, the UsageEvent,
   AIOperation and AIProviderAttempt rows it wrote, and the customer's
   remaining credits. Every provider answer reports distinct token counts, so
   a changed count shows. No network call is made and no key is real.

   With ``JASPEN_PROVIDER_CAPTURE_OUT=<file>`` the run writes what it saw; with
   ``JASPEN_PROVIDER_BASELINE=<file>`` it compares against a run recorded
   earlier on the accepted commit: request bytes always, and results too when
   the recording has them. Recordings contain prompts, so they stay out of the
   repository. Without either variable every case still runs and the routed
   cases check their usage exactly (those numbers come from the scripted
   provider, not from any prompt).

2. A structural guard: no provider SDK is imported, and no provider endpoint is
   addressed, outside app/ai_providers.
"""

import ast
import io
import json
import os
import pathlib
from datetime import datetime

import httpx
import pytest
import requests
from werkzeug.security import generate_password_hash

from app import db as _db
from app.models import AIOperation, AIProviderAttempt, UsageEvent, User


CONTINUE_URL = "/api/v1/ai-agent/conversation/continue"
THREAD_ID = "p5a_thread_fixed"
USER_ID = "p5a-user-0000-0000-0000-000000000001"
FINAL_TEXT = "Here is where the rubric stands."
PNG_BYTES = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
    b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)
PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n"
MODELS = {
    "claude_haiku": "claude-haiku-4-5",
    "claude_sonnet": "claude-sonnet-4-6",
    "claude_opus": "claude-opus-4-6",
    "gemini_flash": "gemini-2.5-flash",
    "gemini_pro": "gemini-3.8-flash",
}
ABSENT = object()


@pytest.fixture(autouse=True)
def _no_rate_limits():
    from app import limiter
    original = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = original


# --------------------------------------------------------------------------
# scripted provider usage: distinct per call, so any change to a count shows
# --------------------------------------------------------------------------

def anthropic_usage(call_index):
    return {"input_tokens": 100 + 7 * call_index, "output_tokens": 11 + 3 * call_index}


def gemini_usage(call_index):
    prompt, completion = 40 + 5 * call_index, 8 + 2 * call_index
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion}


# --------------------------------------------------------------------------
# recorded transports
# --------------------------------------------------------------------------

def _anthropic_message(content, *, model, stop_reason="end_turn", usage=None):
    return {
        "id": "msg_p5a", "type": "message", "role": "assistant", "model": model,
        "content": content, "stop_reason": stop_reason, "stop_sequence": None,
        "usage": usage or {"input_tokens": 50, "output_tokens": 10},
    }


def _sse(event, data):
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _anthropic_stream_body(content, *, model, stop_reason, usage):
    parts = [_sse("message_start", {"type": "message_start", "message": {
        **_anthropic_message([], model=model, stop_reason=None),
        "usage": {"input_tokens": usage["input_tokens"], "output_tokens": 1},
    }})]
    for index, block in enumerate(content):
        if block["type"] == "text":
            parts.append(_sse("content_block_start", {
                "type": "content_block_start", "index": index, "content_block": {"type": "text", "text": ""},
            }))
            words = block["text"].split(" ")
            for position, word in enumerate(words):
                piece = word if position == len(words) - 1 else word + " "
                parts.append(_sse("content_block_delta", {
                    "type": "content_block_delta", "index": index,
                    "delta": {"type": "text_delta", "text": piece},
                }))
        else:
            parts.append(_sse("content_block_start", {
                "type": "content_block_start", "index": index,
                "content_block": {"type": "tool_use", "id": block["id"], "name": block["name"], "input": {}},
            }))
            parts.append(_sse("content_block_delta", {
                "type": "content_block_delta", "index": index,
                "delta": {"type": "input_json_delta", "partial_json": json.dumps(block["input"])},
            }))
        parts.append(_sse("content_block_stop", {"type": "content_block_stop", "index": index}))
    parts.append(_sse("message_delta", {
        "type": "message_delta", "delta": {"stop_reason": stop_reason, "stop_sequence": None},
        "usage": {"output_tokens": usage["output_tokens"]},
    }))
    parts.append(_sse("message_stop", {"type": "message_stop"}))
    return "".join(parts).encode("utf-8")


class _Recorder:
    """Holds the scripted answers and every request a provider received."""

    def __init__(self):
        self.requests = []
        self.anthropic_script = []
        self.gemini_script = []
        self.anthropic_failures = 0
        self.anthropic_refuses = False
        self.gemini_usage = None  # None: varying standard usage; ABSENT: no usage; else this dict
        self.anthropic_calls = 0
        self.gemini_calls = 0

    # Anthropic -------------------------------------------------------------
    def anthropic_handler(self, request):
        body = request.content.decode("utf-8")
        self.requests.append({
            "provider": "anthropic", "method": request.method, "url": str(request.url),
            "anthropic_version": request.headers.get("anthropic-version"),
            "body": body,
        })
        payload = json.loads(body)
        model = payload.get("model")
        if self.anthropic_failures:
            self.anthropic_failures -= 1
            return httpx.Response(529, headers={"retry-after-ms": "1"}, json={
                "type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"},
            })
        usage = anthropic_usage(self.anthropic_calls)
        self.anthropic_calls += 1
        tool_names = {tool.get("name") for tool in payload.get("tools") or []}
        is_reply = "show_scoring_rubric" in tool_names
        if "record_turn_capture" in tool_names:
            content = [{"type": "tool_use", "id": "toolu_capture", "name": "record_turn_capture", "input": {
                "decisions": [], "notes": [], "condition_updates": [], "outcomes": [], "lessons": [],
                "task_commitments": [], "unclear": [],
            }}]
        elif self.anthropic_refuses and (is_reply or not tool_names):
            content = []
        elif is_reply and self.anthropic_script:
            content = self.anthropic_script.pop(0)
        else:
            content = [{"type": "text", "text": FINAL_TEXT if is_reply else "{}"}]
        if not content:
            stop = "refusal"
        else:
            stop = "tool_use" if any(block["type"] == "tool_use" for block in content) else "end_turn"
        if payload.get("stream"):
            return httpx.Response(
                200, headers={"content-type": "text/event-stream"},
                content=_anthropic_stream_body(content, model=model, stop_reason=stop, usage=usage),
            )
        return httpx.Response(200, json=_anthropic_message(content, model=model, stop_reason=stop, usage=usage))

    def anthropic_factory(self, real_cls):
        recorder = self

        def build(*args, **kwargs):
            recorder.requests.append({"provider": "anthropic", "client": {
                "args": list(args), "kwargs": {key: kwargs[key] for key in sorted(kwargs)},
            }})
            return real_cls(
                *args, **kwargs,
                http_client=httpx.Client(transport=httpx.MockTransport(recorder.anthropic_handler)),
            )
        return build

    # Gemini ----------------------------------------------------------------
    def gemini_post(self, url, **kwargs):
        prepared = requests.Request(
            "POST", url, headers=kwargs.get("headers"), json=kwargs.get("json"),
        ).prepare()
        self.requests.append({
            "provider": "gemini", "method": "POST", "url": url,
            "headers": dict(prepared.headers),
            "timeout": list(kwargs.get("timeout")) if isinstance(kwargs.get("timeout"), tuple) else kwargs.get("timeout"),
            "stream": kwargs.get("stream"),
            "body": prepared.body.decode("utf-8"),
        })
        payload = kwargs.get("json") or {}
        tool_names = {(tool.get("function") or {}).get("name") for tool in payload.get("tools") or []}
        is_reply = "show_scoring_rubric" in tool_names
        step = self.gemini_script.pop(0) if (is_reply and self.gemini_script) else {"content": FINAL_TEXT if is_reply else "{}"}
        usage = gemini_usage(self.gemini_calls) if self.gemini_usage is None else self.gemini_usage
        self.gemini_calls += 1
        return _GeminiResponse(step, stream=bool(kwargs.get("stream")), usage=usage)


class _GeminiResponse:
    status_code = 200

    def __init__(self, step, *, stream, usage):
        self.step = step
        self.stream = stream
        self.usage = usage

    def raise_for_status(self):
        return None

    def json(self):
        message = {"role": "assistant", "content": self.step.get("content")}
        if self.step.get("tool_calls"):
            message["tool_calls"] = self.step["tool_calls"]
        body = {"choices": [{"index": 0, "message": message,
                             "finish_reason": "tool_calls" if self.step.get("tool_calls") else "stop"}]}
        if self.usage is not ABSENT:
            body["usage"] = self.usage
        return body

    def iter_lines(self, decode_unicode=False):
        if self.step.get("tool_calls"):
            for index, call in enumerate(self.step["tool_calls"]):
                arguments = call["function"]["arguments"]
                half = len(arguments) // 2
                yield "data: " + json.dumps({"choices": [{"index": 0, "delta": {"tool_calls": [{
                    "index": index, "id": call["id"], "type": "function",
                    "function": {"name": call["function"]["name"], "arguments": arguments[:half]},
                }]}}]})
                yield ""
                yield "data: " + json.dumps({"choices": [{"index": 0, "delta": {"tool_calls": [{
                    "index": index, "function": {"arguments": arguments[half:]},
                }]}}]})
        else:
            for word in str(self.step.get("content") or "").split(" "):
                yield "data: " + json.dumps({"choices": [{"index": 0, "delta": {"content": word + " "}}]})
        if self.usage is not ABSENT:
            # usage arrives only in a final usage-only chunk (no choices)
            yield "data: " + json.dumps({"choices": [], "usage": self.usage})
        yield "data: [DONE]"


# --------------------------------------------------------------------------
# people and projects (fixed ids so the prompts are the same every run)
# --------------------------------------------------------------------------

def _seed_user_and_project(history=None):
    from app.billing_config import consume_credits, release_consumed_credits
    from app.routes.sessions import save_user_sessions

    user = User(
        id=USER_ID, email="p5a-capture@example.test", name="Capture",
        password_hash=generate_password_hash("ValidPass1", method="pbkdf2:sha256"),
        subscription_plan="free", subscription_status="active",
        credits_remaining=1_000_000, seat_limit=5, max_seats=5,
    )
    _db.session.add(user)
    _db.session.commit()
    ok, _ = consume_credits(user, 1)
    assert ok
    release_consumed_credits(user, 1)
    _db.session.commit()
    assert save_user_sessions(user.id, {THREAD_ID: {
        "session_id": THREAD_ID, "user_id": user.id, "name": "Regional contract",
        "status": "in_progress", "visibility": "private",
        "created": "2026-11-01T00:00:00", "timestamp": "2026-11-01T00:00:00",
        "chat_history": history if history is not None else [
            {"role": "user", "content": "Should we bid on the regional contract?",
             "timestamp": "2026-11-01T00:00:00"},
            {"role": "assistant", "content": "What matters most in this decision?",
             "timestamp": "2026-11-01T00:00:01"},
            {"role": "user", "content": "Margin and delivery risk.", "timestamp": "2026-11-01T00:00:02",
             "attachments": [{"name": "notes.txt", "text_excerpt": "Margin floor is 12%."}]},
            {"role": "assistant", "content": "Understood. What is the bid deadline?",
             "timestamp": "2026-11-01T00:00:03"},
        ],
    }})
    return user


def _headers(user):
    from flask_jwt_extended import create_access_token
    return {"Authorization": f"Bearer {create_access_token(identity=str(user.id))}"}


def _sse_events(response):
    events = []
    for chunk in response.get_data(as_text=True).split("\n\n"):
        chunk = chunk.strip()
        if chunk.startswith("data:"):
            try:
                events.append(json.loads(chunk[5:].strip()))
            except ValueError:
                events.append({"unparsed": chunk})
    return events


def _event_shape(event):
    """The provider-driven part of a stream event: its type and, for text and
    tools, the content the provider produced; plus the usage the final event
    reports. Ids and timings come from the route and are left out."""
    kind = event.get("type")
    shape = {"type": kind}
    for key in ("text", "tool"):
        if key in event:
            shape[key] = event[key]
    if isinstance(event.get("usage"), dict):
        shape["usage"] = _without_timing(event["usage"])
    return shape


_TIMING_KEYS = {"duration_ms", "elapsed_ms", "created_at", "updated_at", "settled_at", "timestamp", "operation_id"}


def _without_timing(value):
    """Drop wall-clock fields (durations, timestamps) and generated operation
    ids from a result. Request bodies are never passed through this."""
    if isinstance(value, dict):
        return {key: _without_timing(item) for key, item in value.items() if key not in _TIMING_KEYS}
    if isinstance(value, list):
        return [_without_timing(item) for item in value]
    return value


def _usage_view(usage):
    return _without_timing(usage) if isinstance(usage, dict) else usage


def _credit_records():
    """What the case wrote that billing and audit read."""
    _db.session.expire_all()

    def number(value):
        return None if value is None else str(value)

    events = [
        {"provider": row.provider, "model": row.model, "model_type": row.model_type, "plan_key": row.plan_key,
         "endpoint": row.endpoint, "operation_type": row.operation_type,
         "input_tokens": row.input_tokens, "output_tokens": row.output_tokens, "total_tokens": row.total_tokens,
         "credits_charged": row.credits_charged, "reserved_credits": row.reserved_credits,
         "settled_credits": row.settled_credits, "raw_provider_cost_usd": number(row.raw_provider_cost_usd)}
        for row in UsageEvent.query.order_by(UsageEvent.id).all()
    ]
    operations = [
        {"operation_type": row.operation_type, "status": row.status, "customer_visible": row.customer_visible,
         "subsidized": row.subsidized, "router_mode": row.router_mode,
         "legacy": [row.legacy_provider, row.legacy_model], "selected": [row.selected_provider, row.selected_model],
         "final": [row.final_provider, row.final_model],
         "successful_provider_cost_usd": number(row.successful_provider_cost_usd),
         "total_provider_cost_usd": number(row.total_provider_cost_usd),
         "projected_credits": row.projected_credits, "charged_credits": row.charged_credits,
         "error_code": row.error_code}
        for row in AIOperation.query.all()
    ]
    operations.sort(key=lambda item: json.dumps(item, sort_keys=True, default=str))
    attempts = [
        {"sequence": row.sequence, "provider": row.provider, "model": row.model, "outcome": row.outcome,
         "status_code": row.status_code, "input_tokens": row.input_tokens, "output_tokens": row.output_tokens,
         "raw_provider_cost_usd": number(row.raw_provider_cost_usd), "customer_billable": row.customer_billable,
         "error_code": row.error_code}
        for row in AIProviderAttempt.query.all()
    ]
    attempts.sort(key=lambda item: json.dumps(item, sort_keys=True, default=str))
    user = _db.session.get(User, USER_ID)
    return {"usage_events": events, "operations": operations, "provider_attempts": attempts,
            "credits_remaining": getattr(user, "credits_remaining", None)}


# --------------------------------------------------------------------------
# cases
# --------------------------------------------------------------------------

def _routed(messages, model_type, llm_model, **kwargs):
    from app.routes import ai_agent
    return ai_agent._generate_routed_chat_reply(
        messages, {"model_type": model_type, "llm_model": llm_model},
        system_prompt="P5a fixed system prompt.", operation_type="strategy_generation", **kwargs,
    )


def _case_routed_anthropic(app, recorder, monkeypatch):
    reply, usage = _routed(
        [
            {"role": "user", "content": "Summarise the bid."},
            {"role": "assistant", "content": "It is a regional contract."},
            {"role": "user", "content": "And the main risk?"},
        ],
        "orbit", MODELS["claude_sonnet"], max_tokens=600, temperature=0.3,
    )
    return {"reply": reply, "usage": _usage_view(usage)}


def _case_routed_sonnet5_no_temperature(app, recorder, monkeypatch):
    monkeypatch.setitem(app.config, "LLM_PROVIDER_MODELS", {**MODELS, "claude_sonnet": "claude-sonnet-5-5"})
    reply, usage = _routed([{"role": "user", "content": "One line on the bid."}], "orbit", "claude-sonnet-5-5")
    return {"reply": reply, "usage": _usage_view(usage)}


def _case_routed_failover_to_gemini(app, recorder, monkeypatch):
    recorder.anthropic_failures = 3  # the SDK's own two retries, then failover
    reply, usage = _routed([{"role": "user", "content": "Which option is safer?"}], "orbit", MODELS["claude_sonnet"])
    return {"reply": reply, "usage": _usage_view(usage)}


def _case_routed_all_fail(app, recorder, monkeypatch):
    monkeypatch.setitem(app.config, "GEMINI_API_KEY", "")
    recorder.anthropic_failures = 3
    try:
        _routed([{"role": "user", "content": "Which option is safer?"}], "pluto", MODELS["claude_haiku"])
    except Exception as exc:  # the last provider error is raised to the caller
        return {"error_class": exc.__class__.__name__, "usage": _usage_view(getattr(exc, "jaspen_usage", None))}
    return {"error_class": None}


def _case_routed_anthropic_refusal(app, recorder, monkeypatch):
    recorder.anthropic_refuses = True
    reply, usage = _routed([{"role": "user", "content": "Help with something refused."}], "orbit", MODELS["claude_sonnet"])
    return {"reply": reply, "usage": _usage_view(usage)}


def _gemini_only(app, monkeypatch):
    monkeypatch.setitem(app.config, "ANTHROPIC_API_KEY", "")


def _case_routed_gemini_usage(app, recorder, monkeypatch, usage):
    _gemini_only(app, monkeypatch)
    recorder.gemini_usage = usage
    reply, result_usage = _routed([{"role": "user", "content": "Which option is safer?"}], "orbit", MODELS["claude_sonnet"])
    return {"reply": reply, "usage": _usage_view(result_usage)}


def _continue(client, user, message, *, stream=False, files=None):
    url = CONTINUE_URL + ("?stream=1" if stream else "")
    if files:
        data = {"thread_id": THREAD_ID, "message": message,
                "files": [(io.BytesIO(content), name, media) for name, content, media in files]}
        return client.post(url, headers=_headers(user), data=data, content_type="multipart/form-data")
    return client.post(url, headers=_headers(user), json={"thread_id": THREAD_ID, "message": message})


def _turn_result(response, stream):
    if stream:
        return {"status": response.status_code, "events": [_event_shape(e) for e in _sse_events(response)]}
    payload = response.get_json() or {}
    return {"status": response.status_code, "reply": payload.get("reply") or payload.get("message"),
            "tools": [item.get("tool") for item in payload.get("actions") or []],
            "usage": _usage_view(payload.get("usage"))}


def _anthropic_tool_script():
    return [
        [{"type": "tool_use", "id": "toolu_p5a_1", "name": "show_scoring_rubric", "input": {}}],
        [{"type": "text", "text": FINAL_TEXT}],
    ]


def _gemini_tool_script():
    return [
        {"content": None, "tool_calls": [{"id": "call_p5a_1", "type": "function", "function": {
            "name": "show_scoring_rubric", "arguments": json.dumps({"note": "current"}),
        }}]},
        {"content": FINAL_TEXT},
    ]


def _case_turn_anthropic_tools(app, recorder, client, monkeypatch, stream=False):
    user = _seed_user_and_project()
    recorder.anthropic_script = _anthropic_tool_script()
    return _turn_result(_continue(client, user, "Show me the rubric.", stream=stream), stream)


def _case_turn_anthropic_refusal(app, recorder, client, monkeypatch):
    user = _seed_user_and_project()
    recorder.anthropic_refuses = True
    return _turn_result(_continue(client, user, "Help with something refused."), False)


def _case_turn_gemini_tools(app, recorder, client, monkeypatch, stream=False):
    _gemini_only(app, monkeypatch)
    user = _seed_user_and_project()
    recorder.gemini_script = _gemini_tool_script()
    return _turn_result(_continue(client, user, "Show me the rubric.", stream=stream), stream)


def _case_turn_anthropic_attachments(app, recorder, client, monkeypatch):
    user = _seed_user_and_project()
    return _turn_result(_continue(client, user, "What do these show?", files=[
        ("chart.png", PNG_BYTES, "image/png"),
        ("brief.pdf", PDF_BYTES, "application/pdf"),
    ]), False)


def _case_turn_first_message(app, recorder, client, monkeypatch):
    user = _seed_user_and_project(history=[])
    return _turn_result(_continue(client, user, "We are deciding whether to bid on a regional contract."), False)


def _case_turn_capture(app, recorder, client, monkeypatch, sonnet_model=None):
    from app.routes import ai_agent
    if sonnet_model:
        monkeypatch.setitem(app.config, "LLM_PROVIDER_MODELS", {**MODELS, "claude_sonnet": sonnet_model})
    user = _seed_user_and_project()
    monkeypatch.setattr(ai_agent, "_capture_pass_options", lambda _cards: [
        {"option_key": "opt_bid", "name": "Bid", "jaspen_recommendation": None},
        {"option_key": "opt_pass", "name": "Pass", "jaspen_recommendation": None},
    ])
    result = ai_agent._run_turn_capture(
        user=user, user_id=user.id, thread_id=THREAD_ID,
        user_message="We will bid, and Sam owns the pricing by Friday.",
    )
    return {"summary": result.get("summary"), "usage": _usage_view(result.get("usage"))}


# The first twelve are the original P5a cases; the rest were added for usage.
CASES = {
    "routed_anthropic": lambda app, rec, client, mp: _case_routed_anthropic(app, rec, mp),
    "routed_sonnet5_no_temperature": lambda app, rec, client, mp: _case_routed_sonnet5_no_temperature(app, rec, mp),
    "routed_failover_to_gemini": lambda app, rec, client, mp: _case_routed_failover_to_gemini(app, rec, mp),
    "routed_all_providers_fail": lambda app, rec, client, mp: _case_routed_all_fail(app, rec, mp),
    "turn_anthropic_tools": lambda app, rec, client, mp: _case_turn_anthropic_tools(app, rec, client, mp),
    "turn_anthropic_tools_stream": lambda app, rec, client, mp: _case_turn_anthropic_tools(app, rec, client, mp, stream=True),
    "turn_gemini_tools": lambda app, rec, client, mp: _case_turn_gemini_tools(app, rec, client, mp),
    "turn_gemini_tools_stream": lambda app, rec, client, mp: _case_turn_gemini_tools(app, rec, client, mp, stream=True),
    "turn_anthropic_attachments": lambda app, rec, client, mp: _case_turn_anthropic_attachments(app, rec, client, mp),
    "turn_first_message": lambda app, rec, client, mp: _case_turn_first_message(app, rec, client, mp),
    "turn_capture_forced_tool": lambda app, rec, client, mp: _case_turn_capture(app, rec, client, mp),
    "turn_capture_auto_tool": lambda app, rec, client, mp: _case_turn_capture(app, rec, client, mp, "claude-sonnet-5-5"),
    "routed_anthropic_refusal": lambda app, rec, client, mp: _case_routed_anthropic_refusal(app, rec, mp),
    "routed_gemini_standard_usage": lambda app, rec, client, mp: _case_routed_gemini_usage(app, rec, mp, None),
    "routed_gemini_alternative_usage_keys": lambda app, rec, client, mp: _case_routed_gemini_usage(
        app, rec, mp, {"input_tokens": 33, "output_tokens": 9}),
    "routed_gemini_missing_usage": lambda app, rec, client, mp: _case_routed_gemini_usage(app, rec, mp, ABSENT),
    "routed_gemini_zero_usage": lambda app, rec, client, mp: _case_routed_gemini_usage(
        app, rec, mp, {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}),
    "turn_anthropic_refusal": lambda app, rec, client, mp: _case_turn_anthropic_refusal(app, rec, client, mp),
}
ORIGINAL_CASES = list(CASES)[:12]


class _FixedDatetime(datetime):
    """The route stamps tool results and capture context with the clock; a
    fixed clock keeps the recorded bodies identical from run to run."""

    @classmethod
    def utcnow(cls):
        return cls(2026, 11, 17, 12, 0, 0)

    @classmethod
    def now(cls, tz=None):
        return cls(2026, 11, 17, 12, 0, 0, tzinfo=tz)


def _run_case(name, app, client, db, monkeypatch):
    import anthropic
    from app.routes import ai_agent

    with monkeypatch.context() as mp:
        rec = _Recorder()
        mp.setattr(ai_agent, "datetime", _FixedDatetime)
        mp.setattr(anthropic, "Anthropic", rec.anthropic_factory(anthropic.Anthropic))
        mp.setattr(requests, "post", rec.gemini_post)
        for key, value in {
            "ANTHROPIC_API_KEY": "sk-ant-test-not-real",
            "GEMINI_API_KEY": "gemini-test-not-real",
            "GEMINI_API_TIER": "paid",
            "LLM_PROVIDER_MODELS": dict(MODELS),
        }.items():
            mp.setitem(app.config, key, value)
        with app.test_request_context():
            outcome = CASES[name](app, rec, client, mp)
        records = _credit_records()
    return {"requests": rec.requests, "outcome": outcome, "records": records}


def _env_path(name):
    value = os.environ.get(name)
    return pathlib.Path(value) if value else None


def _store_capture(name, result):
    out = _env_path("JASPEN_PROVIDER_CAPTURE_OUT")
    if not out:
        return
    existing = json.loads(out.read_text()) if out.exists() else {}
    existing[name] = result
    out.write_text(json.dumps(existing, indent=1, sort_keys=True))


@pytest.mark.parametrize("case_name", list(CASES))
def test_provider_requests_and_usage_are_unchanged(case_name, app, client, db, monkeypatch):
    result = _run_case(case_name, app, client, db, monkeypatch)
    _store_capture(case_name, result)
    assert any("body" in item for item in result["requests"]), "the case reached no provider"

    baseline_file = _env_path("JASPEN_PROVIDER_BASELINE")
    if baseline_file is None:
        return
    recorded = json.loads(baseline_file.read_text())
    if case_name not in recorded:
        pytest.skip(f"{case_name} is not in this recording")
    baseline = recorded[case_name]
    assert len(result["requests"]) == len(baseline["requests"]), (
        f"{case_name}: {len(result['requests'])} provider requests now, {len(baseline['requests'])} before"
    )
    for index, (now, before) in enumerate(zip(result["requests"], baseline["requests"])):
        assert now == before, f"{case_name}: request {index} differs from the recorded baseline"
    if "records" in baseline:  # recordings made before usage capture hold request bytes only
        assert result["outcome"] == baseline["outcome"], f"{case_name}: returned result or usage differs"
        assert result["records"] == baseline["records"], f"{case_name}: recorded usage or credits differ"


# --------------------------------------------------------------------------
# usage the routed cases must report (numbers come from the scripted provider)
# --------------------------------------------------------------------------

def _tokens(usage):
    return {key: usage.get(key) for key in ("provider", "model", "input_tokens", "output_tokens", "total_tokens")}


@pytest.mark.parametrize("case_name,expected", [
    ("routed_anthropic", {"provider": "anthropic", "model": "claude-sonnet-5",
                          "input_tokens": 100, "output_tokens": 11, "total_tokens": 111}),
    ("routed_anthropic_refusal", {"provider": "anthropic", "model": "claude-sonnet-5",
                                  "input_tokens": 100, "output_tokens": 11, "total_tokens": 111}),
    ("routed_failover_to_gemini", {"provider": "gemini", "model": "gemini-3.8-flash",
                                   "input_tokens": 40, "output_tokens": 8, "total_tokens": 48}),
    ("routed_gemini_standard_usage", {"provider": "gemini", "model": "gemini-3.8-flash",
                                      "input_tokens": 40, "output_tokens": 8, "total_tokens": 48}),
    ("routed_gemini_alternative_usage_keys", {"provider": "gemini", "model": "gemini-3.8-flash",
                                              "input_tokens": 33, "output_tokens": 9, "total_tokens": 42}),
    ("routed_gemini_missing_usage", {"provider": "gemini", "model": "gemini-3.8-flash",
                                     "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}),
    ("routed_gemini_zero_usage", {"provider": "gemini", "model": "gemini-3.8-flash",
                                  "input_tokens": 0, "output_tokens": 0, "total_tokens": 0}),
])
def test_routed_replies_report_provider_usage_exactly(case_name, expected, app, client, db, monkeypatch):
    usage = _run_case(case_name, app, client, db, monkeypatch)["outcome"]["usage"]
    assert _tokens(usage) == expected


def test_routed_refusal_is_a_reply_with_its_usage(app, client, db, monkeypatch):
    outcome = _run_case("routed_anthropic_refusal", app, client, db, monkeypatch)["outcome"]
    assert outcome["reply"].strip()
    assert outcome["usage"]["refused"] is True and outcome["usage"]["stop_reason"] == "refusal"


def test_failover_records_the_failed_attempt_then_the_answer(app, client, db, monkeypatch):
    usage = _run_case("routed_failover_to_gemini", app, client, db, monkeypatch)["outcome"]["usage"]
    attempts = usage["failover"]["attempted_providers"]
    assert [(item["provider"], item["outcome"], item["status_code"]) for item in attempts] == [
        ("anthropic", "overloaded", 529)]
    assert usage["failover"]["final_provider"] == "gemini" and usage["failover"]["failover_count"] == 1


@pytest.mark.parametrize("case_name", ["turn_anthropic_tools_stream", "turn_gemini_tools_stream"])
def test_stream_event_order_is_tool_then_result_then_text(case_name, app, client, db, monkeypatch):
    """A streamed tool turn reports the tool call, its result, then the reply
    text as it arrives, on both providers."""
    events = _run_case(case_name, app, client, db, monkeypatch)["outcome"]["events"]
    kinds = [event["type"] for event in events]
    assert kinds.index("tool_use") < kinds.index("tool_result") < kinds.index("delta")
    assert "".join(event.get("text", "") for event in events if event["type"] == "delta").strip() == FINAL_TEXT


# --------------------------------------------------------------------------
# the provider boundary
# --------------------------------------------------------------------------

APP_DIR = pathlib.Path(__file__).resolve().parents[1] / "app"
PROVIDER_DIR = APP_DIR / "ai_providers"
PROVIDER_SDKS = {"anthropic", "openai", "google.generativeai", "google.genai", "vertexai", "mistralai", "cohere"}
PROVIDER_ENDPOINTS = ("api.anthropic.com", "generativelanguage.googleapis.com", "api.openai.com")


def _is_sdk(module_name):
    name = str(module_name or "")
    return any(name == sdk or name.startswith(sdk + ".") for sdk in PROVIDER_SDKS)


def _boundary_violations(path):
    tree = ast.parse(path.read_text(), filename=str(path))
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.extend(f"import {alias.name}" for alias in node.names if _is_sdk(alias.name))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and _is_sdk(node.module):
            found.append(f"from {node.module} import ...")
        elif isinstance(node, ast.Call):
            callee = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if callee in {"import_module", "__import__"} and node.args and isinstance(node.args[0], ast.Constant) \
                    and _is_sdk(node.args[0].value):
                found.append(f"{callee}({node.args[0].value!r})")
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.extend(f"endpoint {host}" for host in PROVIDER_ENDPOINTS if host in node.value)
    return found


def test_provider_sdks_and_endpoints_only_in_ai_providers():
    violations = []
    for path in sorted(APP_DIR.rglob("*.py")):
        if PROVIDER_DIR in path.parents:
            continue
        violations.extend(f"{path.relative_to(APP_DIR.parent)}: {item}" for item in _boundary_violations(path))
    assert violations == [], "provider SDK or endpoint outside app/ai_providers: " + ", ".join(violations)


def test_the_guard_sees_what_it_guards(tmp_path):
    sample = tmp_path / "sample.py"
    sample.write_text(
        "import anthropic\nfrom google.genai import types\n"
        "def f():\n    import openai\n    return 'https://api.anthropic.com/v1/messages'\n"
    )
    assert _boundary_violations(sample) == [
        "import anthropic", "from google.genai import ...", "import openai", "endpoint api.anthropic.com",
    ]


def test_provider_package_loads_no_sdk_at_import_and_imports_no_route():
    for path in sorted(PROVIDER_DIR.glob("*.py")):
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if isinstance(node, ast.Import):
                assert not any(_is_sdk(alias.name) for alias in node.names), f"{path.name}: SDK imported at module load"
            if isinstance(node, ast.ImportFrom):
                assert not _is_sdk(node.module), f"{path.name}: SDK imported at module load"
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                module = ("." * node.level) + (node.module or "")
                assert "routes" not in module, f"{path.name} imports a route module ({module})"


def test_provider_modules_do_not_depend_on_each_other():
    """Shared reading of stored content lives in ai_providers.content."""
    for path in sorted(PROVIDER_DIR.glob("*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.ImportFrom) and node.level:
                names = {alias.name for alias in node.names}
                assert not ({node.module} | names) & {"anthropic", "gemini"}, f"{path.name} imports another provider"


COMPATIBILITY_ONLY_NAMES = (
    "_anthropic_text", "_anthropic_model_accepts_temperature", "_anthropic_request_timeout_seconds",
    "_gemini_request_timeouts", "_anthropic_content_to_dicts", "_parse_openai_tool_call_arguments",
)


def test_no_test_relies_on_patching_a_compatibility_only_name():
    """These old ai_agent names are kept for imports only: patching them does
    not reach the provider code (see the note in routes/ai_agent.py)."""
    tests_dir = pathlib.Path(__file__).resolve().parent
    offenders = []
    for path in sorted(tests_dir.rglob("test_*.py")):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "setattr":
                for arg in node.args[1:2]:
                    if isinstance(arg, ast.Constant) and arg.value in COMPATIBILITY_ONLY_NAMES:
                        offenders.append(f"{path.name}:{node.lineno} {arg.value}")
    assert offenders == []
