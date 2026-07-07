# backend/app/routes/public_intake.py
#
# Pre-signup homepage intake — the front door to the SAME Jaspen readiness
# determination the authenticated workspace uses.
#
# Launch mode (Option A, per 2026-07-06 decision review): deterministic only.
# POST /analyze imports ONLY from app.intake_readiness — no Anthropic import,
# no model call, no session, no cost, no abuse surface beyond a free
# keyword-matching endpoint. It answers exactly one question: does Jaspen
# have enough to build a scorecard, using the identical engine
# (_compute_readiness / _is_ready_to_analyze / _next_question) the
# authenticated workspace runs. There is no separate "public readiness" —
# see tests/test_public_intake.py::TestEquivalence.
#
# The pre-signup AI-chat design (real streaming reply, tool-free, Pluto-tier)
# is fully built but PARKED behind PUBLIC_INTAKE_AI_ENABLED (default false).
# With the flag off, /chat is disabled and no anonymous Anthropic call can
# happen — see tests/test_public_intake.py::TestNoAiPreauthGuarantee.
# Do not enable in production before: a hard spend ceiling, abuse/rate-limit
# testing behind real infrastructure (proxies/CDN), and a live-key staging run.

import os

from flask import Blueprint, jsonify, request

from app import limiter
from app.intake_readiness import (
    MAX_USER_MESSAGE_LENGTH,
    _active_readiness_spec,
    _compute_readiness,
    _is_ready_to_analyze,
    _next_question,
)

public_intake_bp = Blueprint("public_intake", __name__)


def _public_intake_ai_enabled():
    return str(os.getenv("PUBLIC_INTAKE_AI_ENABLED", "false")).strip().lower() in ("1", "true", "yes", "on")


def _sanitize_history(raw):
    """Keep only well-formed {role, content} turns; role must be user/assistant."""
    if not isinstance(raw, list):
        return []
    cleaned = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip().lower()
        content = str(item.get("content") or "").strip()
        if role not in ("user", "assistant") or not content:
            continue
        cleaned.append({"role": role, "content": content})
    return cleaned


def _user_authored_length(chat_history):
    return sum(len(m["content"]) for m in chat_history if m["role"] == "user")


def _band_for(ready, overall_percent):
    if ready:
        return "ready"
    if overall_percent >= 35:
        return "building"
    return "starting"


def deterministic_reply_text(ready, next_question, is_first_turn):
    """The one and only deterministic assistant reply. Mirrors
    frontend/src/homeSections/HomePage/InteractiveDecisionHero.jsx's
    assistantBubbleFor() exactly — kept in sync by hand since the two run in
    different languages; if you change one, change both.

    This is also what /chat (see _public_intake_chat.py) falls back to
    whenever the AI can't produce a reply for any reason — the visitor gets
    the SAME sentence Option A would have given them, never a generic error.
    """
    if ready:
        return "You've told Jaspen enough to start building a scorecard on this."
    question = next_question or "Tell me more about what you're working through."
    return question if is_first_turn else f"Got it. {question}"


@public_intake_bp.route("/analyze", methods=["POST"])
@limiter.limit("20 per minute")
def analyze_intake():
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

    spec = _active_readiness_spec()
    readiness = _compute_readiness(chat_history, strategy_objective="balanced", spec=spec)
    ready = _is_ready_to_analyze(readiness)
    overall_percent = int((readiness.get("overall") or {}).get("percent") or 0)

    categories = readiness.get("categories") or []
    known = [
        {"key": c.get("key"), "label": c.get("label")}
        for c in categories
        if c.get("completed")
    ]
    missing = [
        {"key": c.get("key"), "label": c.get("label"), "required": bool(c.get("required"))}
        for c in categories
        if not c.get("completed")
    ]

    return jsonify({
        "spec_version": readiness.get("version") or spec.get("version"),
        "ready": ready,
        "overall_percent": overall_percent,
        "band": _band_for(ready, overall_percent),
        "known": known,
        "missing": missing,
        "next_question": None if ready else _next_question(readiness),
        "characters_used": used,
        "characters_remaining": max(0, MAX_USER_MESSAGE_LENGTH - used),
    }), 200


@public_intake_bp.route("/chat", methods=["POST"])
@limiter.limit("8 per minute")
@limiter.limit("40 per hour")
def public_chat():
    if not _public_intake_ai_enabled():
        return jsonify({
            "error": "Pre-signup AI chat is not enabled.",
            "code": "public_intake_ai_disabled",
        }), 404

    # Imported lazily, only when the flag is on, so importing this module and
    # calling /analyze never touches anthropic or ai_agent.py's AI-specific
    # helpers at all — the no-AI guarantee holds structurally, not just by
    # config, when the flag is off.
    from ._public_intake_chat import stream_public_chat_response
    return stream_public_chat_response(request)
