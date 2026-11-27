"""Gemini adapter, through Google's OpenAI-compatible chat completions endpoint.

The only module that addresses the Gemini endpoint. It speaks plain HTTP
(``requests``), so there is no SDK to import. The API key, model choice and
the user-message fencing rules stay with the caller and are passed in.
"""

import json
import os

import requests
from flask import current_app

from . import observer as provider_observer
from .content import block_text
from .usage import reported_error_usage


OPENAI_COMPAT_URL = "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"


def request_timeouts():
    connect_value = (
        current_app.config.get("AI_AGENT_GEMINI_CONNECT_TIMEOUT_SECONDS")
        or os.getenv("AI_AGENT_GEMINI_CONNECT_TIMEOUT_SECONDS")
        or 20
    )
    read_value = (
        current_app.config.get("AI_AGENT_GEMINI_READ_TIMEOUT_SECONDS")
        or os.getenv("AI_AGENT_GEMINI_READ_TIMEOUT_SECONDS")
        or 60
    )
    try:
        connect_timeout = max(5.0, float(connect_value))
    except Exception:
        connect_timeout = 20.0
    try:
        read_timeout = max(5.0, float(read_value))
    except Exception:
        read_timeout = 60.0
    return (connect_timeout, read_timeout)


# ---------------------------------------------------------------------------
# requests: Jaspen -> OpenAI-compatible format
# ---------------------------------------------------------------------------

def tools_from_definitions(definitions):
    """Jaspen's tool definitions (Messages API shape) as function tools."""
    tools = []
    for item in definitions:
        if not isinstance(item, dict):
            continue
        tools.append({
            "type": "function",
            "function": {
                "name": item.get("name"),
                "description": item.get("description"),
                "parameters": item.get("input_schema") or {
                    "type": "object",
                    "properties": {},
                    "additionalProperties": False,
                },
            },
        })
    return tools


def messages_from_history(messages, *, message_text, user_content):
    """Conversation messages as chat completion messages.

    ``message_text(item)`` reads a message's text and ``user_content(text)``
    gives the content a user message is sent with; both are the caller's.
    """
    output = []
    for item in messages or []:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = item.get("content")
        text_content = message_text(item)
        if role not in {"assistant", "user", "tool"}:
            continue
        if isinstance(content, str):
            payload = {
                "role": role,
                "content": text_content if role != "user" else user_content(text_content),
            }
            if role == "assistant" and isinstance(item.get("tool_calls"), list):
                payload["tool_calls"] = item.get("tool_calls")
            if role == "tool" and item.get("tool_call_id"):
                payload["tool_call_id"] = item.get("tool_call_id")
            output.append(payload)
            continue
        if role == "assistant" and isinstance(content, list):
            assistant_text = block_text(content)
            if assistant_text:
                output.append({"role": "assistant", "content": assistant_text})
    return output


def chat_completion(*, model_name, system_prompt, messages, tools, max_tokens, temperature, api_key, stream=False):
    """POST one chat completion. ``messages`` are already in chat format.

    Returns the ``requests`` response; raises on an HTTP error status.
    """
    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system_prompt},
            *messages,
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = "auto"
    if stream:
        payload["stream"] = True
        payload["stream_options"] = {"include_usage": True}

    call = provider_observer.announce(
        "google", model_name, max_output_tokens=max_tokens,
        input_chars=provider_observer.input_characters(system_prompt, messages, tools),
    )
    try:
        response = requests.post(
            OPENAI_COMPAT_URL,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=request_timeouts(),
            stream=stream,
        )
        response.raise_for_status()
    except Exception as exc:
        if call is not None:
            input_tokens, output_tokens = reported_error_usage(exc)
            call.report("failed", input_tokens=input_tokens, output_tokens=output_tokens, error=exc,
                        status_code=getattr(getattr(exc, "response", None), "status_code", None))
        raise
    if call is not None:
        if stream:
            response._jaspen_observed_call = call  # reported when iter_stream_payloads ends
        else:
            usage = {}
            try:
                usage = (response.json() or {}).get("usage") or {}
            except Exception:  # an unreadable body: usage unknown
                usage = {}
            call.report("succeeded", input_tokens=usage.get("prompt_tokens"),
                        output_tokens=usage.get("completion_tokens"), status_code=response.status_code)
    return response


# ---------------------------------------------------------------------------
# responses: OpenAI-compatible format -> Jaspen
# ---------------------------------------------------------------------------

def first_choice(payload):
    """``(choice, message)`` of a chat completion's first choice."""
    choice = ((payload.get("choices") or [{}])[0]) if isinstance(payload, dict) else {}
    message = choice.get("message") if isinstance(choice, dict) else {}
    message = message if isinstance(message, dict) else {}
    return choice, message


def finish_reason(choice):
    """The choice's finish reason, or None when it has none."""
    return str(choice.get("finish_reason") or "").strip() or None


def message_text(message):
    """The visible text of a chat completion message."""
    return str(message.get("content") or "").strip()


def message_tool_calls(message):
    """The tool calls a chat completion message asks for."""
    return message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []


def tool_call_request(tool_call):
    """``(tool_name, tool_input)`` of one requested tool call."""
    function = tool_call.get("function") if isinstance(tool_call, dict) else {}
    tool_name = str((function or {}).get("name") or "").strip()
    tool_input = parse_tool_call_arguments((function or {}).get("arguments"))
    return tool_name, tool_input


def assistant_tool_call_message(content, tool_calls):
    """The model's tool-calling turn, echoed back into the conversation."""
    return {
        "role": "assistant",
        "content": content,
        "tool_calls": tool_calls,
    }


def tool_result_message(tool_call, result_payload):
    """The tool-role message that answers one tool call."""
    return {
        "role": "tool",
        "tool_call_id": tool_call.get("id"),
        "content": json.dumps(result_payload),
    }


def parse_tool_call_arguments(raw_arguments):
    raw_text = str(raw_arguments or "").strip()
    if not raw_text:
        return {}
    try:
        data = json.loads(raw_text)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def usage_to_internal(usage, *, provider, model):
    usage = usage if isinstance(usage, dict) else {}
    input_tokens = int(
        usage.get("prompt_tokens")
        or usage.get("input_tokens")
        or 0
    )
    output_tokens = int(
        usage.get("completion_tokens")
        or usage.get("output_tokens")
        or 0
    )
    total_tokens = int(usage.get("total_tokens") or (input_tokens + output_tokens))
    return {
        "provider": provider,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
    }


def iter_stream_payloads(response):
    """Yield each JSON chunk of a streamed chat completion, in order.

    An observed call (see ``chat_completion``) is reported when the stream ends:
    succeeded with the last usage chunk, or abandoned or failed when it stops early.
    """
    call = getattr(response, "_jaspen_observed_call", None)
    usage = {}
    try:
        for raw_line in response.iter_lines(decode_unicode=True):
            line = str(raw_line or "").strip()
            if not line.startswith("data:"):
                continue
            data_text = line[5:].strip()
            if not data_text or data_text == "[DONE]":
                continue
            payload = json.loads(data_text)
            if isinstance(payload, dict) and isinstance(payload.get("usage"), dict):
                usage = payload["usage"]
            yield payload
    except GeneratorExit:
        if call is not None:
            call.report("abandoned", input_tokens=usage.get("prompt_tokens"),
                        output_tokens=usage.get("completion_tokens"))
        raise
    except Exception as exc:
        if call is not None:
            call.report("failed", input_tokens=usage.get("prompt_tokens"),
                        output_tokens=usage.get("completion_tokens"), error=exc)
        raise
    if call is not None:
        call.report("succeeded", input_tokens=usage.get("prompt_tokens"),
                    output_tokens=usage.get("completion_tokens"), status_code=getattr(response, "status_code", None))


def stream_chunk(payload):
    """``(usage, delta)`` of one streamed chunk.

    ``usage`` is the chunk's usage object when it carries one (usage-only
    chunks included), else None. ``delta`` is the first choice's delta, or
    None when the chunk has no usable delta.
    """
    usage = (payload.get("usage") or {}) if isinstance(payload.get("usage"), dict) else None
    choices = payload.get("choices") if isinstance(payload, dict) else None
    if not isinstance(choices, list) or not choices:
        return usage, None
    delta = (choices[0] or {}).get("delta") if isinstance(choices[0], dict) else {}
    if not isinstance(delta, dict):
        return usage, None
    return usage, delta


def delta_text(delta):
    return str(delta.get("content") or "")


def delta_tool_calls(delta):
    return delta.get("tool_calls") if isinstance(delta.get("tool_calls"), list) else []


def merge_tool_call_delta(tool_calls_by_index, tool_delta):
    """Fold one streamed tool-call fragment into the calls gathered so far."""
    idx = int(tool_delta.get("index", len(tool_calls_by_index)))
    existing = tool_calls_by_index.setdefault(idx, {
        "id": tool_delta.get("id"),
        "type": "function",
        "function": {"name": "", "arguments": ""},
    })
    if tool_delta.get("id"):
        existing["id"] = tool_delta.get("id")
    function = tool_delta.get("function") if isinstance(tool_delta.get("function"), dict) else {}
    if function.get("name"):
        existing["function"]["name"] = str(function.get("name"))
    if function.get("arguments"):
        existing["function"]["arguments"] += str(function.get("arguments"))
