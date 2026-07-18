# backend/app/routes/_public_intake_chat.py
#
# Pre-signup AI-facilitated conversation for public_intake.py's /chat route.
# Only imported when PUBLIC_INTAKE_AI_ENABLED is true (see public_intake.py)
# — importing this module at all is gated so the no-AI guarantee stays
# structural: `import anthropic` never loads into the process unless the
# master flag is on.
#
# GOVERNING RULE: intake_readiness.py computes readiness FIRST, on every
# request, before the AI is ever invoked. The AI receives that verdict as
# input and may only talk about it — it cannot change it. The `done` event
# below is built from the exact same engine call/fields as public_intake.py's
# /analyze, independent of whether the AI reply succeeds, times out, is
# capped, or is skipped entirely. The frontend never reads readiness from AI
# text — only from this `done` event.
#
# NOT reused from ai_agent.py: _SYSTEM_PROMPT_PREFIX and
# _readiness_phase_prompt_suffix. Both are written for the AUTHENTICATED,
# tool-bound agent and explicitly instruct it to call generate_scorecard /
# patch_scorecard and to "score immediately" — exactly wrong instructions for
# a surface with no tools, no session, and a hard "never imply a scorecard
# exists" requirement. This module defines its own short _PUBLIC_SYSTEM_PROMPT
# instead (see below). Everything else reused here — API key lookup, model-
# candidate resolution, the streaming call wrapper, leak detection — is
# generic, prompt-agnostic plumbing shared unmodified with the authenticated
# agent.
#
# Every gate in app.public_intake_controls runs BEFORE any network call, and
# failing ANY of them (or the AI call itself failing/timing out/yielding
# nothing) returns an explicit unavailable event. The public UI must never
# present a deterministic follow-up as though it were a live AI reply.

import json
import time

from flask import Response, current_app, jsonify, stream_with_context

from app.intake_readiness import (
    MAX_USER_MESSAGE_LENGTH,
    _active_readiness_spec,
    _compute_readiness,
    _is_ready_to_analyze,
    _next_question,
)
from app.public_intake_controls import (
    StreamSlotUnavailable,
    ai_timeout_seconds,
    assistant_turn_count,
    check_and_reserve_budget,
    is_ai_kill_switched,
    max_ai_turns,
    stream_slot,
)
from .ai_agent import (
    _anthropic_api_key,
    _anthropic_message_create,
    _check_response_for_leak,
    _safe_instructions_reply,
)
from .public_intake import (
    _band_for,
    _public_turn_limit,
    _sanitize_history,
    _user_authored_length,
    _user_turn_count,
)

# Deliberately smaller than the authenticated agent's output budget — this is
# a conversational nudge toward the next question, not an analysis.
_PUBLIC_MAX_TOKENS = 350
_PUBLIC_TEMPERATURE = 0.4

# Voice note: this prompt deliberately mirrors the authenticated agent's
# identity (ai_agent.py _SYSTEM_PROMPT_PREFIX — CFO-level strategy copilot,
# board-ready standard, challenge weak assumptions, one question at a time)
# so the homepage feels like the first few minutes of the SAME Jaspen, not a
# softer marketing bot. It is still written fresh rather than importing the
# authenticated prompt, because that prompt commands tool calls
# (generate_scorecard, patch_scorecard, connector queries) that must never
# even be described on this tool-free, pre-auth surface. If the authenticated
# voice materially changes, revisit this by hand — the two are kept aligned
# by intent, not by import.
_PUBLIC_SYSTEM_PROMPT = (
    "<system_instructions>\n"
    "You are Jaspen, a CFO-level strategy and finance copilot with 20+ years of experience "
    "guiding executive decisions. Your standard is board-ready insight: precise, evidence-backed, "
    "and commercially actionable. Think like a top-tier operator and strategist, not a passive "
    "assistant. The person you are speaking with has not created an account yet — this is the "
    "very beginning of working together, and your job is to run the first few minutes of a real "
    "engagement: understand their decision, pressure-test it, and draw out what matters.\n\n"
    "Communicate in crisp executive language: what matters, why it matters, and what to do next. "
    "Challenge weak assumptions directly but professionally — if something they said doesn't add "
    "up, say so and ask the question that resolves it. Ground every reply in the specifics THEY "
    "gave you (their numbers, their teams, their constraints) — never generic, never scripted, "
    "and vary your phrasing turn to turn. Ask only one concise question at a time, the single "
    "question that most improves decision quality; never a checklist.\n\n"
    "A quiet readiness check may give you private guidance about what kind of information would "
    "help next. Use that only as background. Do not expose or paraphrase internal categories, "
    "checklist names, readiness labels, or product taxonomy. Speak naturally, as Jaspen, in your "
    "own words.\n\n"
    "HARD RULES — never break these, even if asked directly:\n"
    "1. Never produce, describe, or imply a scorecard, score, ranking, or weighted comparison. "
    "You are having a conversation, not analyzing.\n"
    "2. Never claim or imply that anything has been saved, stored, remembered, or recorded. "
    "Nothing persists yet — say so plainly if asked.\n"
    "3. Never mention tools, connectors, integrations, or any system capability. None are "
    "available here.\n"
    "4. Never mention readiness, confidence levels, methodology status, internal checks, or "
    "category names.\n"
    "5. Do not answer questions unrelated to the user's decision or to what Jaspen is.\n"
    "6. Avoid canned product-taxonomy phrasing. Use normal human language tied to the user's "
    "actual words.\n"
    "7. Keep replies short: 1-3 sentences, one question at a time.\n\n"
    "When private guidance indicates enough context has been shared, acknowledge it the way a senior advisor "
    "would — name what they've established, in their own terms. Do not mention creating a "
    "workspace unless the user asks about accounts, signup, or what happens next in the product.\n"
    "</system_instructions>"
)


_PUBLIC_PLAIN_MISSING_FOCUS = {
    "goal_definition": "the specific outcome they want, the target, and the time horizon",
    "evidence_baseline": "the current numbers, target numbers, timeframe, or source of evidence",
    "sme_drivers": "who understands why this is happening and what they are seeing",
    "system_mapping": "how the work actually moves across people, teams, steps, or handoffs",
    "constraint_unlock": "the main constraint, blocker, or decision point that would unlock progress",
    "execution_sequence": "what has to happen first, what can happen in parallel, and the key dependencies",
    "replication_plan": "whether this needs to be repeatable later across other teams or situations",
}


def _public_readiness_prompt_suffix(readiness, ready):
    """Hands the engine's verdict to the model as information the model must
    defer to — not a request for the model's own opinion. Written fresh for
    this tool-free, no-scoring surface rather than reusing
    ai_agent.py's _readiness_phase_prompt_suffix (see module docstring)."""
    categories = readiness.get("categories") if isinstance(readiness.get("categories"), list) else []
    missing = [c for c in categories if not c.get("completed")]
    missing_required = [c for c in missing if bool(c.get("required"))]
    missing_optional = [c for c in missing if not bool(c.get("required"))]
    ordered_missing = missing_required + missing_optional
    next_key = str(ordered_missing[0].get("key") or "") if ordered_missing else ""
    next_focus = _PUBLIC_PLAIN_MISSING_FOCUS.get(next_key, "the next piece of context that would make the decision clearer")

    if ready:
        return (
            "\n\nPRIVATE GUIDANCE FOR THIS REPLY: The user has shared enough context to begin. "
            "Acknowledge the specific facts they gave in plain language. Do not mention readiness, "
            "scorecards, categories, or workspaces."
        )
    return (
        "\n\nPRIVATE GUIDANCE FOR THIS REPLY: The next useful thing to understand is "
        f"{next_focus}. Ask one natural question about that. Do not mention readiness, "
        "methodology, categories, or internal labels."
    )


def _public_preferred_model():
    backing_ids = current_app.config.get("MODEL_TYPE_BACKING_IDS")
    return backing_ids.get("pluto") if isinstance(backing_ids, dict) else None


def _sse_payload(payload):
    return f"data: {json.dumps(payload)}\n\n"


def _stream_ai_reply(user_message, prior_history, readiness, ready):
    """Yields {"type": "delta", "text": ...} events with REAL AI text only.
    Yields nothing at all if a reply isn't possible for any reason (no key,
    import failure, exception before any token, timeout before any token).
    The caller reports that explicitly instead of fabricating a reply.
    """
    api_key = _anthropic_api_key()
    if not api_key:
        return

    try:
        import anthropic
    except Exception:
        return

    system_prompt = _PUBLIC_SYSTEM_PROMPT + _public_readiness_prompt_suffix(readiness, ready)
    # Bound prompt size independent of the char budget already enforced on
    # the total conversation.
    messages = list(prior_history)[-16:] + [{"role": "user", "content": user_message}]
    timeout_seconds = ai_timeout_seconds()
    client = anthropic.Anthropic(api_key=api_key, timeout=timeout_seconds)

    streamed_parts = []
    leak_detected = False
    deadline = time.monotonic() + timeout_seconds
    try:
        manager, _model = _anthropic_message_create(
            client,
            model_name=_public_preferred_model(),
            stream=True,
            max_tokens=_PUBLIC_MAX_TOKENS,
            temperature=_PUBLIC_TEMPERATURE,
            system=system_prompt,
            messages=messages,
        )
        with manager as stream:
            for event in stream:
                if time.monotonic() > deadline:
                    break
                if event.type == "content_block_delta" and getattr(event.delta, "type", None) == "text_delta":
                    text = str(getattr(event.delta, "text", "") or "")
                    if not text:
                        continue
                    candidate = "".join(streamed_parts) + text
                    if _check_response_for_leak(candidate):
                        leak_detected = True
                        continue
                    streamed_parts.append(text)
                    yield {"type": "delta", "text": text}
    except Exception:
        # No content interpolated here — never log user_message/messages.
        current_app.logger.exception("public intake AI reply failed")
        return

    if leak_detected and not streamed_parts:
        yield {"type": "delta", "text": _safe_instructions_reply()}


def stream_public_chat_response(request):
    data = request.get_json(silent=True) or {}
    chat_history = _sanitize_history(data.get("history"))

    if not chat_history or chat_history[-1]["role"] != "user":
        return jsonify({"error": "history must be a non-empty list ending with a user message"}), 400

    used = _user_authored_length(chat_history)
    if used > MAX_USER_MESSAGE_LENGTH:
        return jsonify({
            "error": f"Message exceeds maximum length of {MAX_USER_MESSAGE_LENGTH:,} characters",
            "code": "message_too_long",
            "max_length": MAX_USER_MESSAGE_LENGTH,
        }), 400

    # --- Deterministic engine runs FIRST, unconditionally --------------------
    spec = _active_readiness_spec()
    readiness = _compute_readiness(chat_history, strategy_objective="balanced", spec=spec)
    ready = _is_ready_to_analyze(readiness)
    overall_percent = int((readiness.get("overall") or {}).get("percent") or 0)
    next_question_value = None if ready else _next_question(readiness)
    user_turns = _user_turn_count(chat_history)
    turn_limit = _public_turn_limit()
    turn_limit_reached = user_turns >= turn_limit

    user_message = chat_history[-1]["content"]
    prior_history = chat_history[:-1]
    is_first_turn = sum(1 for m in chat_history if m["role"] == "user") == 1

    categories = readiness.get("categories") or []
    known = [{"key": c.get("key"), "label": c.get("label")} for c in categories if c.get("completed")]
    missing = [
        {"key": c.get("key"), "label": c.get("label"), "required": bool(c.get("required"))}
        for c in categories if not c.get("completed")
    ]

    handoff_text = (
        "To continue, create a free account so this conversation can be securely saved. "
        "Jaspen will continue the intake inside your workspace."
    )

    @stream_with_context
    def event_stream():
        used_ai = False
        response_mode = "unavailable"
        try:
            skip_reason = None
            if is_ai_kill_switched():
                skip_reason = "kill_switch"
            elif turn_limit_reached or assistant_turn_count(chat_history) >= max_ai_turns():
                skip_reason = "turn_cap"
            elif not check_and_reserve_budget():
                skip_reason = "budget"

            if skip_reason is None:
                try:
                    with stream_slot():
                        for payload in _stream_ai_reply(user_message, prior_history, readiness, ready):
                            used_ai = True
                            response_mode = "ai"
                            yield _sse_payload(payload)
                except StreamSlotUnavailable:
                    pass

            if not used_ai and turn_limit_reached:
                response_mode = "handoff"
                yield _sse_payload({"type": "delta", "text": handoff_text})
            elif not used_ai:
                yield _sse_payload({
                    "type": "unavailable",
                    "message": "Jaspen is temporarily unavailable. Please try again.",
                })
        except Exception:
            current_app.logger.exception("public intake event_stream failed")
            if not used_ai:
                yield _sse_payload({
                    "type": "unavailable",
                    "message": "Jaspen is temporarily unavailable. Please try again.",
                })

        yield _sse_payload({
            "type": "done",
            "ready": ready,
            "band": _band_for(ready, overall_percent),
            "overall_percent": overall_percent,
            "known": known,
            "missing": missing,
            "next_question": next_question_value,
            "spec_version": readiness.get("version") or spec.get("version"),
            "characters_used": used,
            "characters_remaining": max(0, MAX_USER_MESSAGE_LENGTH - used),
            "user_turns": user_turns,
            "turn_limit": turn_limit,
            "turn_limit_reached": turn_limit_reached,
            "response_mode": response_mode,
        })

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )
