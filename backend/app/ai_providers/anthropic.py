"""Anthropic Messages API adapter.

The only module that imports the Anthropic SDK. The import is lazy so loading
Jaspen never loads the SDK. Model choice and routing stay with the caller:
``message_create`` receives the candidate model ids already resolved.
"""

import json
import os

from flask import current_app

from .content import block_text


def load_sdk():
    """Import and return the Anthropic SDK; raises if it is not installed."""
    import anthropic

    return anthropic


def request_timeout_seconds():
    value = (
        current_app.config.get("AI_AGENT_ANTHROPIC_TIMEOUT_SECONDS")
        or os.getenv("AI_AGENT_ANTHROPIC_TIMEOUT_SECONDS")
        or 60
    )
    try:
        return max(5.0, float(value))
    except Exception:
        return 60.0


def create_client(api_key):
    """A Messages API client with Jaspen's request timeout."""
    sdk = load_sdk()
    return sdk.Anthropic(api_key=api_key, timeout=request_timeout_seconds())


def model_accepts_temperature(model_name):
    """Return False for current Claude generations that reject temperature."""
    normalized = str(model_name or "").strip().lower()
    return not (
        normalized.startswith("claude-sonnet-5")
        or normalized.startswith("claude-fable-5")
        or normalized.startswith("claude-opus-4-7")
        or normalized.startswith("claude-opus-4-8")
        or normalized.startswith("claude-opus-5")
        or normalized.startswith("claude-mythos-5")
    )


def message_create(client, *, candidates, stream=False, **kwargs):
    """Send one Messages request, trying each candidate model id in order.

    Returns ``(response_or_stream_manager, model_id_used)``. Sampling
    parameters a model rejects are left out of its request.
    """
    last_error = None
    for candidate in candidates:
        if not candidate:
            continue
        try:
            request_kwargs = dict(kwargs)
            if not model_accepts_temperature(candidate):
                request_kwargs.pop("temperature", None)
                request_kwargs.pop("top_p", None)
                request_kwargs.pop("top_k", None)
            if str(candidate).strip().lower().startswith("claude-sonnet-5"):
                # Preserve pre-migration latency, output budgets, and economics.
                # Adaptive thinking can be benchmarked and enabled separately.
                request_kwargs["thinking"] = {"type": "disabled"}
            if stream:
                return client.messages.stream(model=candidate, **request_kwargs), candidate
            return client.messages.create(model=candidate, **request_kwargs), candidate
        except Exception as exc:
            last_error = exc
            continue
    if last_error:
        raise last_error
    raise RuntimeError("No valid Anthropic model candidates configured")


# ---------------------------------------------------------------------------
# requests: Jaspen content -> Messages API blocks
# ---------------------------------------------------------------------------

def attachment_blocks(attachments, *, safe_name, max_text_chars):
    """Conversation attachments as Messages API content blocks.

    Images and PDFs go as base64 sources; Word and data files go as their
    extracted text. ``safe_name`` cleans a file name for display and
    ``max_text_chars`` caps extracted text; both are the caller's rules.
    """
    blocks = []
    for attachment in attachments if isinstance(attachments, list) else []:
        if not isinstance(attachment, dict):
            continue
        encoded = str(attachment.get("data") or "").strip()
        media_type = str(attachment.get("type") or "").strip()
        kind = str(attachment.get("kind") or "").strip().lower()
        if not encoded or not media_type or not kind:
            continue
        if kind == "image":
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": encoded,
                },
            })
        elif kind == "pdf":
            blocks.append({
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": encoded,
                },
            })
        elif kind in ("word", "data"):
            extracted_text = str(attachment.get("text_content") or "").strip()
            attachment_name = safe_name(attachment.get("name") or "document")
            label = "Word Document" if kind == "word" else "Uploaded File (cell/row content)"
            if extracted_text:
                blocks.append({
                    "type": "text",
                    "text": (
                        f"[{label}: {attachment_name}]\n"
                        f"{extracted_text[:max_text_chars]}"
                    ),
                })
    return blocks


def content_to_dicts(content_blocks):
    """Normalize SDK content blocks to dicts containing ONLY the canonical
    fields the Anthropic API accepts on round-trip. model_dump() can include
    extra fields (e.g. parsed_output on newer Haiku models) that the API
    rejects with 'Extra inputs are not permitted'."""
    normalized = []
    for block in (content_blocks or []):
        block_type = (
            block.get("type") if isinstance(block, dict)
            else getattr(block, "type", "text")
        )
        if block_type == "text":
            text_val = (
                block.get("text") if isinstance(block, dict)
                else getattr(block, "text", "")
            )
            normalized.append({"type": "text", "text": str(text_val or "")})
        elif block_type == "tool_use":
            tu_id = block.get("id") if isinstance(block, dict) else getattr(block, "id", None)
            tu_name = block.get("name") if isinstance(block, dict) else getattr(block, "name", None)
            tu_input = block.get("input") if isinstance(block, dict) else getattr(block, "input", None)
            normalized.append({
                "type": "tool_use",
                "id": tu_id,
                "name": tu_name,
                "input": tu_input if isinstance(tu_input, (dict, list)) else {},
            })
        elif block_type == "tool_result":
            tr_id = block.get("tool_use_id") if isinstance(block, dict) else getattr(block, "tool_use_id", None)
            tr_content = block.get("content") if isinstance(block, dict) else getattr(block, "content", "")
            normalized.append({
                "type": "tool_result",
                "tool_use_id": tr_id,
                "content": tr_content if isinstance(tr_content, str) else json.dumps(tr_content),
            })
        # silently drop unknown block types (thinking, etc.) — they aren't
        # accepted as input by the API anyway
    return normalized


# ---------------------------------------------------------------------------
# responses: Messages API -> Jaspen
# ---------------------------------------------------------------------------

text = block_text


def response_text(response):
    """Return visible text while treating an HTTP-200 refusal as a result."""
    visible = text(getattr(response, "content", None))
    if visible:
        return visible
    if str(getattr(response, "stop_reason", "") or "").strip().lower() == "refusal":
        return "I’m unable to help with that request."
    return ""


def stop_reason(message):
    """The message's stop reason, or None when it has none."""
    return str(getattr(message, "stop_reason", "") or "").strip() or None


def is_refusal(message):
    """True when the model ended the message by refusing (HTTP 200)."""
    return str(getattr(message, "stop_reason", "") or "").lower() == "refusal"


def reply_usage(response, *, model):
    """Normalized usage of one non-tool reply, in Jaspen's usage shape."""
    input_tokens, output_tokens = usage_counts(response)
    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": int(input_tokens + output_tokens),
        "provider": "anthropic",
        "model": model,
        "stop_reason": stop_reason(response),
        "refused": is_refusal(response),
    }


def usage_counts(response):
    """``(input_tokens, output_tokens)`` reported on a message (0 when absent)."""
    usage = getattr(response, "usage", None)
    return (
        int(getattr(usage, "input_tokens", 0) or 0),
        int(getattr(usage, "output_tokens", 0) or 0),
    )


def tool_use_blocks(content_blocks):
    """The tool_use blocks of a message's content, SDK objects or dicts."""
    return [
        block for block in (content_blocks or [])
        if getattr(block, "type", None) == "tool_use" or (isinstance(block, dict) and block.get("type") == "tool_use")
    ]


def tool_use_call(block):
    """``(tool_name, tool_use_id, tool_input)`` of one tool_use block."""
    if isinstance(block, dict):
        tool_name = str(block.get("name") or "").strip()
        tool_use_id = block.get("id")
        tool_input = block.get("input") if isinstance(block.get("input"), dict) else {}
    else:
        tool_name = str(getattr(block, "name", "") or "").strip()
        tool_use_id = getattr(block, "id", None)
        raw_input = getattr(block, "input", None)
        tool_input = raw_input if isinstance(raw_input, dict) else {}
    return tool_name, tool_use_id, tool_input


def tool_result_block(tool_use_id, result_payload):
    """A tool result, as the content block that answers a tool_use block."""
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": json.dumps(result_payload),
    }


def tool_round_messages(assistant_content, tool_results):
    """The two messages one tool round adds to the conversation: the model's
    turn (echoed back in API-accepted form) and the user turn with the results."""
    return [
        {"role": "assistant", "content": content_to_dicts(assistant_content)},
        {"role": "user", "content": tool_results},
    ]


def iter_text_deltas(stream):
    """Yield each non-empty text delta of a Messages stream, in order."""
    for event in stream:
        if event.type == "content_block_delta" and getattr(event.delta, "type", None) == "text_delta":
            delta_text = str(getattr(event.delta, "text", "") or "")
            if delta_text:
                yield delta_text
