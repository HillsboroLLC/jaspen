from __future__ import annotations
from flask import Blueprint, request, jsonify, make_response
from typing import Any, Dict
import secrets, time

from app.services.context_store import set_context

discuss_bp = Blueprint("discuss", __name__)

def _ensure_session_id() -> str:
    sid = request.cookies.get("sekki_sid")
    if isinstance(sid, str) and sid:
        return sid
    # Generate new, short, collision-safe session id
    return "conv_" + secrets.token_hex(6)

def discuss_start_legacy():
    data: Dict[str, Any] = request.get_json(silent=True) or {}
    analysis_id = data.get("analysis_id")
    analysis_obj = data.get("analysis") or {}
    if not analysis_id and not analysis_obj:
        return jsonify({"error": "analysis_id or analysis object required"}), 400

    # Build a compact context envelope. Accept whatever fields the caller has.
    ctx: Dict[str, Any] = {
        "analysis_id": analysis_id or analysis_obj.get("id"),
        "summary": analysis_obj.get("summary") or data.get("summary"),
        "score": analysis_obj.get("score") or data.get("score"),
        "components": analysis_obj.get("components") or data.get("components"),
        "meta": {
            "source": "discuss_start",
            "ts": int(time.time()),
        },
        # keep the raw object if provided (bounded trust)
        "raw": analysis_obj if isinstance(analysis_obj, dict) else None,
    }

    sid = _ensure_session_id()
    set_context(sid, ctx, ttl=2*60*60)

    resp = make_response(jsonify({"ok": True, "session_id": sid, "context_keys": [k for k,v in ctx.items() if v]}), 200)
    # Only set cookie when new
    if "sekki_sid" not in request.cookies:
        # SameSite=None because frontend is on sekki.io and API is api.sekki.io
        resp.set_cookie("sekki_sid", sid, secure=True, samesite="None", path="/", max_age=30*24*60*60)
    return resp
