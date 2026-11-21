"""Provider adapters (app/ai_providers): request construction, response and
stream decoding, and usage normalization, checked with structured data.

Nothing here depends on a system prompt or on model-written text, so these
tests stay valid when prompts change. The route-level byte comparison lives in
test_ai_providers.py.
"""

import json
import types

import pytest
import requests

from app.ai_providers import anthropic as claude
from app.ai_providers import gemini
from app.ai_providers.content import block_text


# --------------------------------------------------------------------------
# Anthropic: client and request construction
# --------------------------------------------------------------------------

def test_client_gets_the_key_and_the_configured_timeout(app, monkeypatch):
    import anthropic

    built = []
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kwargs: built.append(kwargs) or "client")
    with app.app_context():
        monkeypatch.setitem(app.config, "AI_AGENT_ANTHROPIC_TIMEOUT_SECONDS", None)
        monkeypatch.delenv("AI_AGENT_ANTHROPIC_TIMEOUT_SECONDS", raising=False)
        assert claude.create_client("k1") == "client"
        monkeypatch.setitem(app.config, "AI_AGENT_ANTHROPIC_TIMEOUT_SECONDS", "2")
        claude.create_client("k2")
        monkeypatch.setitem(app.config, "AI_AGENT_ANTHROPIC_TIMEOUT_SECONDS", "not-a-number")
        claude.create_client("k3")
    assert built == [
        {"api_key": "k1", "timeout": 60.0},
        {"api_key": "k2", "timeout": 5.0},
        {"api_key": "k3", "timeout": 60.0},
    ]


def _recording_client():
    calls = []
    client = types.SimpleNamespace(messages=types.SimpleNamespace(
        create=lambda **kwargs: calls.append(("create", kwargs)) or "message",
        stream=lambda **kwargs: calls.append(("stream", kwargs)) or "manager",
    ))
    return client, calls


def test_sampling_parameters_follow_what_each_model_accepts():
    client, calls = _recording_client()
    assert claude.message_create(client, candidates=["claude-haiku-4-5"], temperature=0.2, max_tokens=5) == (
        "message", "claude-haiku-4-5")
    assert calls[-1] == ("create", {"model": "claude-haiku-4-5", "temperature": 0.2, "max_tokens": 5})

    assert claude.message_create(client, candidates=["", "claude-sonnet-5-5"], stream=True,
                                 temperature=0.2, top_p=0.9, top_k=5, max_tokens=5) == ("manager", "claude-sonnet-5-5")
    assert calls[-1] == ("stream", {"model": "claude-sonnet-5-5", "max_tokens": 5, "thinking": {"type": "disabled"}})

    claude.message_create(client, candidates=["claude-opus-5"], temperature=0.2, max_tokens=5)
    assert calls[-1] == ("create", {"model": "claude-opus-5", "max_tokens": 5})
    for model, accepts in [("claude-haiku-4-5", True), ("claude-sonnet-4-6", True), ("claude-sonnet-5", False),
                           ("claude-opus-4-8", False), ("claude-fable-5-2", False), ("claude-mythos-5-1", False)]:
        assert claude.model_accepts_temperature(model) is accepts, model


def test_message_create_tries_the_next_candidate_then_raises_the_last_error():
    seen = []

    def create(**kwargs):
        seen.append(kwargs["model"])
        raise ValueError(kwargs["model"])

    client = types.SimpleNamespace(messages=types.SimpleNamespace(create=create))
    with pytest.raises(ValueError, match="second"):
        claude.message_create(client, candidates=["first", "second"])
    assert seen == ["first", "second"]
    with pytest.raises(RuntimeError, match="No valid Anthropic model candidates"):
        claude.message_create(client, candidates=[None, ""])


def test_attachments_become_base64_blocks_or_capped_text():
    blocks = claude.attachment_blocks([
        {"kind": "image", "type": "image/png", "data": "aW1n"},
        {"kind": "pdf", "type": "application/pdf", "data": "cGRm"},
        {"kind": "word", "type": "application/msword", "data": "x", "name": "plan.docx", "text_content": "abcdef"},
        {"kind": "data", "type": "text/csv", "data": "x", "name": "rows.csv", "text_content": "  r1  "},
        {"kind": "word", "type": "application/msword", "data": "x", "name": "empty.docx", "text_content": ""},
        {"kind": "image", "type": "", "data": "aW1n"},
        "not an attachment",
    ], safe_name=lambda name: f"<{name}>", max_text_chars=3)
    assert blocks == [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "aW1n"}},
        {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "cGRm"}},
        {"type": "text", "text": "[Word Document: <plan.docx>]\nabc"},
        {"type": "text", "text": "[Uploaded File (cell/row content): <rows.csv>]\nr1"},
    ]
    assert claude.attachment_blocks(None, safe_name=str, max_text_chars=1) == []


# --------------------------------------------------------------------------
# Anthropic: tool round trip, streaming, usage, refusal
# --------------------------------------------------------------------------

def test_tool_round_trip_echoes_only_api_fields_and_answers_each_call():
    sdk_blocks = [
        types.SimpleNamespace(type="text", text="Checking.", citations=None),
        types.SimpleNamespace(type="tool_use", id="toolu_1", name="show_scoring_rubric", input={"a": 1},
                              parsed_output="extra field the API rejects"),
        types.SimpleNamespace(type="thinking", thinking="dropped"),
    ]
    calls = [claude.tool_use_call(block) for block in claude.tool_use_blocks(sdk_blocks)]
    assert calls == [("show_scoring_rubric", "toolu_1", {"a": 1})]
    assert claude.tool_use_call({"type": "tool_use", "id": "t2", "name": " x ", "input": "bad"}) == ("x", "t2", {})

    results = [claude.tool_result_block("toolu_1", {"ok": True, "rows": [1]})]
    assert claude.tool_round_messages(sdk_blocks, results) == [
        {"role": "assistant", "content": [
            {"type": "text", "text": "Checking."},
            {"type": "tool_use", "id": "toolu_1", "name": "show_scoring_rubric", "input": {"a": 1}},
        ]},
        {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": "toolu_1", "content": json.dumps({"ok": True, "rows": [1]})},
        ]},
    ]
    assert claude.content_to_dicts([{"type": "tool_result", "tool_use_id": "t", "content": [{"x": 1}]}]) == [
        {"type": "tool_result", "tool_use_id": "t", "content": json.dumps([{"x": 1}])}]


def test_stream_yields_text_deltas_in_order_and_nothing_else():
    def event(kind, delta_type=None, text=None):
        return types.SimpleNamespace(type=kind, delta=types.SimpleNamespace(type=delta_type, text=text))

    stream = [
        event("message_start"),
        event("content_block_delta", "text_delta", "Hel"),
        event("content_block_delta", "input_json_delta", "{}"),
        event("content_block_delta", "text_delta", ""),
        event("content_block_delta", "text_delta", "lo"),
        event("message_delta"),
    ]
    assert list(claude.iter_text_deltas(stream)) == ["Hel", "lo"]


def test_anthropic_usage_counts_and_reply_usage():
    message = types.SimpleNamespace(usage=types.SimpleNamespace(input_tokens=123, output_tokens=45),
                                    stop_reason=" end_turn ", content=[])
    assert claude.usage_counts(message) == (123, 45)
    assert claude.usage_counts(types.SimpleNamespace()) == (0, 0)
    assert claude.usage_counts(types.SimpleNamespace(usage=types.SimpleNamespace(input_tokens=None))) == (0, 0)
    assert claude.reply_usage(message, model="claude-x") == {
        "input_tokens": 123, "output_tokens": 45, "total_tokens": 168,
        "provider": "anthropic", "model": "claude-x", "stop_reason": "end_turn", "refused": False,
    }
    assert list(claude.reply_usage(message, model="m")) == [
        "input_tokens", "output_tokens", "total_tokens", "provider", "model", "stop_reason", "refused"]
    assert claude.stop_reason(types.SimpleNamespace()) is None


def test_refusal_is_a_visible_result_with_its_usage_kept():
    """Structure only: the refusal wording is the AI layer's (Article 17A
    follow-up) and is not pinned here."""
    refused = types.SimpleNamespace(content=[], stop_reason="refusal",
                                    usage=types.SimpleNamespace(input_tokens=9, output_tokens=2))
    assert claude.response_text(refused).strip()
    assert claude.is_refusal(refused) is True
    usage = claude.reply_usage(refused, model="m")
    assert (usage["refused"], usage["stop_reason"], usage["input_tokens"], usage["output_tokens"]) == (
        True, "refusal", 9, 2)

    with_text = types.SimpleNamespace(content=[types.SimpleNamespace(type="text", text="Answer.")], stop_reason="refusal")
    assert claude.response_text(with_text) == "Answer."
    assert claude.response_text(types.SimpleNamespace(content=[], stop_reason="end_turn")) == ""


def test_block_text_joins_text_blocks_of_either_shape():
    assert block_text([
        {"type": "text", "text": "a"}, {"type": "tool_use"}, {"type": "text", "text": ""},
        types.SimpleNamespace(type="text", text="b"), types.SimpleNamespace(type="image"),
    ]) == "a\nb"
    assert block_text(None) == "" and claude.text is block_text


# --------------------------------------------------------------------------
# Gemini: endpoint and request construction
# --------------------------------------------------------------------------

def test_endpoint_is_googles_openai_compatible_chat_completions():
    assert gemini.OPENAI_COMPAT_URL == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


def test_chat_completion_request(app, monkeypatch):
    sent = []

    class Response:
        def raise_for_status(self):
            sent[-1]["checked"] = True

    monkeypatch.setattr(requests, "post", lambda url, **kwargs: sent.append({"url": url, **kwargs}) or Response())
    with app.app_context():
        monkeypatch.setitem(app.config, "AI_AGENT_GEMINI_CONNECT_TIMEOUT_SECONDS", "1")
        monkeypatch.setitem(app.config, "AI_AGENT_GEMINI_READ_TIMEOUT_SECONDS", "90")
        gemini.chat_completion(model_name="gemini-x", system_prompt="S", messages=[{"role": "user", "content": "u"}],
                               tools=[], max_tokens=10, temperature=0.2, api_key="KEY")
        gemini.chat_completion(model_name="gemini-x", system_prompt="S", messages=[], tools=[{"type": "function"}],
                               max_tokens=10, temperature=0.2, api_key="KEY", stream=True)
    plain, streamed = sent
    assert plain["url"] == gemini.OPENAI_COMPAT_URL
    assert plain["headers"] == {"Authorization": "Bearer KEY", "Content-Type": "application/json"}
    assert plain["timeout"] == (5.0, 90.0) and plain["stream"] is False and plain["checked"]
    assert plain["json"] == {"model": "gemini-x", "messages": [{"role": "system", "content": "S"},
                                                               {"role": "user", "content": "u"}],
                             "temperature": 0.2, "max_tokens": 10}
    assert list(plain["json"]) == ["model", "messages", "temperature", "max_tokens"]
    assert streamed["stream"] is True
    assert {key: streamed["json"][key] for key in ("tools", "tool_choice", "stream", "stream_options")} == {
        "tools": [{"type": "function"}], "tool_choice": "auto", "stream": True,
        "stream_options": {"include_usage": True}}


def test_chat_completion_raises_on_http_error(app, monkeypatch):
    class Response:
        def raise_for_status(self):
            raise requests.exceptions.HTTPError("503")

    monkeypatch.setattr(requests, "post", lambda url, **kwargs: Response())
    with app.app_context(), pytest.raises(requests.exceptions.HTTPError):
        gemini.chat_completion(model_name="m", system_prompt="S", messages=[], tools=[], max_tokens=1,
                               temperature=0, api_key="K")


def test_tools_take_the_function_shape():
    assert gemini.tools_from_definitions([
        {"name": "a", "description": "A", "input_schema": {"type": "object", "properties": {"x": {}}}},
        {"name": "b", "description": "B"},
        "skip",
    ]) == [
        {"type": "function", "function": {"name": "a", "description": "A",
                                          "parameters": {"type": "object", "properties": {"x": {}}}}},
        {"type": "function", "function": {"name": "b", "description": "B",
                                          "parameters": {"type": "object", "properties": {},
                                                         "additionalProperties": False}}},
    ]


def test_history_roles_convert_with_the_callers_rules():
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "content": "{}", "tool_call_id": "c1"},
        {"role": "assistant", "content": [{"type": "text", "text": "from blocks"}]},
        {"role": "assistant", "content": [{"type": "tool_use"}]},
        {"role": "system", "content": "dropped"},
        "dropped",
    ]
    assert gemini.messages_from_history(
        history, message_text=lambda item: str(item.get("content") or "") if isinstance(item.get("content"), str) else "",
        user_content=lambda text: f"<user>{text}</user>",
    ) == [
        {"role": "user", "content": "<user>hi</user>"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "c1"}]},
        {"role": "tool", "content": "{}", "tool_call_id": "c1"},
        {"role": "assistant", "content": "from blocks"},
    ]


def test_tool_call_echo_and_tool_result_messages():
    call = {"id": "call_1", "type": "function", "function": {"name": " show ", "arguments": '{"x": 1}'}}
    assert gemini.tool_call_request(call) == ("show", {"x": 1})
    assert gemini.tool_call_request("bad") == ("", {})
    assert gemini.assistant_tool_call_message(None, [call]) == {"role": "assistant", "content": None, "tool_calls": [call]}
    assert gemini.tool_result_message(call, {"ok": True}) == {
        "role": "tool", "tool_call_id": "call_1", "content": json.dumps({"ok": True})}
    assert gemini.parse_tool_call_arguments("[1]") == {} and gemini.parse_tool_call_arguments("{bad") == {}
    assert gemini.parse_tool_call_arguments(None) == {}


# --------------------------------------------------------------------------
# Gemini: responses, streams and usage
# --------------------------------------------------------------------------

def test_first_choice_message_text_and_finish_reason():
    choice, message = gemini.first_choice({"choices": [{"message": {"content": "  hi  ", "tool_calls": [1]},
                                                         "finish_reason": " stop "}]})
    assert (gemini.message_text(message), gemini.message_tool_calls(message), gemini.finish_reason(choice)) == (
        "hi", [1], "stop")
    choice, message = gemini.first_choice({"choices": []})
    assert (choice, message, gemini.finish_reason(choice), gemini.message_tool_calls(message)) == ({}, {}, None, [])
    assert gemini.first_choice("not a payload") == ({}, {})


def test_stream_lines_chunks_and_usage_only_chunk():
    response = types.SimpleNamespace(iter_lines=lambda decode_unicode=False: iter([
        "", ": keep-alive", "data:", 'data: {"choices": [{"delta": {"content": "Hi"}}]}', "data: [DONE]",
        '  data: {"choices": [], "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}}  ',
    ]))
    chunks = [gemini.stream_chunk(payload) for payload in gemini.iter_stream_payloads(response)]
    assert chunks == [
        (None, {"content": "Hi"}),
        ({"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9}, None),
    ]
    assert gemini.stream_chunk({"usage": {}, "choices": [{"delta": "bad"}]}) == ({}, None)
    assert gemini.stream_chunk({"usage": "bad", "choices": ["bad"]}) == (None, {})
    assert gemini.delta_text({"content": None}) == "" and gemini.delta_tool_calls({"tool_calls": "x"}) == []


def test_fragmented_tool_calls_assemble_in_index_order():
    calls = {}
    for fragment in [
        {"index": 1, "id": "c2", "function": {"name": "other"}},
        {"index": 0, "id": "c1", "function": {"name": "show", "arguments": '{"x"'}},
        {"index": 0, "function": {"arguments": ": 1}"}},
        {"id": "c3", "function": {"name": "third"}},
    ]:
        gemini.merge_tool_call_delta(calls, fragment)
    assert [calls[index] for index in sorted(calls)] == [
        {"id": "c1", "type": "function", "function": {"name": "show", "arguments": '{"x": 1}'}},
        {"id": "c2", "type": "function", "function": {"name": "other", "arguments": ""}},
        {"id": "c3", "type": "function", "function": {"name": "third", "arguments": ""}},
    ]


@pytest.mark.parametrize("reported,expected", [
    ({"prompt_tokens": 40, "completion_tokens": 8, "total_tokens": 48}, (40, 8, 48)),
    ({"prompt_tokens": 40, "completion_tokens": 8, "total_tokens": 50}, (40, 8, 50)),  # reported total is kept
    ({"prompt_tokens": 40, "completion_tokens": 8}, (40, 8, 48)),                     # total falls back to the sum
    ({"input_tokens": 33, "output_tokens": 9}, (33, 9, 42)),                          # alternative key names
    ({"prompt_tokens": 0, "input_tokens": 5, "completion_tokens": 0, "output_tokens": 3}, (5, 3, 8)),
    ({"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, (0, 0, 0)),     # reported zero
    ({}, (0, 0, 0)),                                                                  # missing usage
    (None, (0, 0, 0)),
    ("bad", (0, 0, 0)),
])
def test_gemini_usage_normalization(reported, expected):
    usage = gemini.usage_to_internal(reported, provider="gemini", model="gemini-x")
    assert usage == {"provider": "gemini", "model": "gemini-x", "input_tokens": expected[0],
                     "output_tokens": expected[1], "total_tokens": expected[2]}


# --------------------------------------------------------------------------
# usage a failed call reported (failover cost records)
# --------------------------------------------------------------------------

def _error(usage=None, response_usage=None):
    exc = RuntimeError("failed")
    if usage is not None:
        exc.usage = usage
    if response_usage is not None:
        exc.response = types.SimpleNamespace(usage=response_usage)
    return exc


@pytest.mark.parametrize("exc,expected", [
    (_error(), (None, None)),                                                         # nothing reported
    (_error({"input_tokens": 12, "output_tokens": 3}), (12, 3)),
    (_error({"prompt_tokens": 12, "completion_tokens": 3}), (12, 3)),
    (_error({"input_tokens": 0, "prompt_tokens": 4}), (4, None)),
    (_error({"input_tokens": 0, "output_tokens": 0}), (None, None)),                  # zero reads as not reported
    (_error(response_usage=types.SimpleNamespace(input_tokens=7, output_tokens=0)), (7, 0)),
    (_error(types.SimpleNamespace(input_tokens=None, output_tokens=2), {"input_tokens": 99}), (None, 2)),
])
def test_reported_error_usage(exc, expected):
    from app.ai_providers.usage import reported_error_usage
    assert reported_error_usage(exc) == expected


def test_failed_attempt_cost_prefers_reported_usage_then_estimates(app):
    from app.routes import ai_agent
    with app.app_context():
        reported = ai_agent._failed_attempt_cost_fields(
            _error({"prompt_tokens": 12, "completion_tokens": 3}), model="gemini-2.5-flash",
            estimated_input_tokens=500, estimated_output_tokens=700, estimate_method="m")
        estimated = ai_agent._failed_attempt_cost_fields(
            _error(), model="gemini-2.5-flash", estimated_input_tokens=500, estimated_output_tokens=700,
            estimate_method="m")
    assert (reported["input_tokens"], reported["output_tokens"], reported["estimate_method"]) == (12, 3, None)
    assert "raw_provider_cost_usd" in reported
    assert estimated == {"input_tokens": 500, "output_tokens": 700, "estimate_method": "m"}
