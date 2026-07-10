# backend/app/public_intake_controls.py
#
# Control plane for the pre-signup AI-facilitated conversation
# (app/routes/_public_intake_chat.py). None of this decides readiness — that
# is intake_readiness.py's job alone. This module only decides whether the AI
# is *allowed to run at all* on a given request. Every check here is cheap,
# local, and fails toward the deterministic path (see each function's
# docstring) — a visitor should never see an error because one of these
# tripped, only a deterministic reply instead of an AI one.
#
# Three independent layers, deliberately not interdependent:
#   1. Kill switch  — operator-controlled, DB-backed (AppSetting), so it is
#      instant and global across every worker/instance without a deploy.
#      This is the ONLY database interaction anywhere on the anonymous
#      intake path, and it reads/writes a single admin-set boolean — zero
#      visitor data. Cached ~30s in-process to keep DB load negligible under
#      real traffic; fails CLOSED (treated as switched off) if the read
#      itself fails, since uncertainty on a cost-bearing surface should
#      degrade to the free path, never to "assume AI is fine."
#   2. Budget breaker — deliberately NOT DB/Redis-backed, so the "no DB
#      persistence pre-auth" guarantee holds without exception for the
#      request itself. In-process only, which means the ceiling is
#      PER WORKER PROCESS and resets on restart/deploy. When tuning
#      PUBLIC_INTAKE_AI_DAILY_REQUEST_LIMIT, divide your intended total daily
#      cap by your gunicorn worker count.
#   3. Concurrency cap — same per-worker caveat as the budget breaker, same
#      reason (no shared store on this path).

import os
import threading
import time
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import AppSetting

KILL_SWITCH_SETTING_KEY = "public_intake_ai_kill_switch"
_KILL_SWITCH_CACHE_TTL_SECONDS = 30

_kill_switch_lock = threading.Lock()
_kill_switch_cache = {"value": None, "checked_at": 0.0}


def _read_kill_switch_row():
    row = db.session.get(AppSetting, KILL_SWITCH_SETTING_KEY)
    if not row or not isinstance(row.value, dict):
        return False
    return bool(row.value.get("disabled"))


def get_kill_switch_state():
    """For the admin view — lets a DB error surface normally (the admin API
    already requires DB access for everything else it does)."""
    row = db.session.get(AppSetting, KILL_SWITCH_SETTING_KEY)
    disabled = bool(row.value.get("disabled")) if row and isinstance(row.value, dict) else False
    return {
        "disabled": disabled,
        "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
    }


def set_kill_switch_state(disabled):
    row = db.session.get(AppSetting, KILL_SWITCH_SETTING_KEY)
    if not row:
        row = AppSetting(key=KILL_SWITCH_SETTING_KEY, value={"disabled": bool(disabled)})
        db.session.add(row)
    else:
        row.value = {"disabled": bool(disabled)}
    return row


def is_ai_kill_switched():
    """True means AI must NOT run for this request. Cached ~30s in-process;
    fails CLOSED (returns True) on any read error."""
    now = time.monotonic()
    with _kill_switch_lock:
        cached = _kill_switch_cache
        if cached["value"] is not None and (now - cached["checked_at"]) < _KILL_SWITCH_CACHE_TTL_SECONDS:
            return cached["value"]
    try:
        disabled = _read_kill_switch_row()
    except SQLAlchemyError:
        disabled = True  # fail closed
    with _kill_switch_lock:
        _kill_switch_cache["value"] = disabled
        _kill_switch_cache["checked_at"] = now
    return disabled


def reset_kill_switch_cache():
    """Test-only helper — clears the in-process cache so a test can flip the
    underlying setting and immediately observe the new value."""
    with _kill_switch_lock:
        _kill_switch_cache["value"] = None
        _kill_switch_cache["checked_at"] = 0.0


# --- Budget breaker (in-process only — see module docstring) ---------------

_budget_lock = threading.Lock()
_budget_state = {"date": None, "count": 0}


def _daily_request_ceiling():
    try:
        return max(0, int(os.getenv("PUBLIC_INTAKE_AI_DAILY_REQUEST_LIMIT", "200")))
    except (TypeError, ValueError):
        return 200


def check_and_reserve_budget():
    """Returns True and reserves one slot if today's per-worker ceiling has
    not been reached; False otherwise. Resets automatically at UTC midnight."""
    today = datetime.now(timezone.utc).date().isoformat()
    ceiling = _daily_request_ceiling()
    with _budget_lock:
        if _budget_state["date"] != today:
            _budget_state["date"] = today
            _budget_state["count"] = 0
        if _budget_state["count"] >= ceiling:
            return False
        _budget_state["count"] += 1
        return True


def reset_budget_state():
    """Test-only helper."""
    with _budget_lock:
        _budget_state["date"] = None
        _budget_state["count"] = 0


# --- Concurrency cap (in-process only — see module docstring) --------------

def _max_concurrent_streams():
    try:
        return max(1, int(os.getenv("PUBLIC_INTAKE_AI_MAX_CONCURRENT_STREAMS", "6")))
    except (TypeError, ValueError):
        return 6


_stream_semaphore = threading.Semaphore(_max_concurrent_streams())


class StreamSlotUnavailable(Exception):
    """Raised when no concurrency slot is free; callers should treat this
    exactly like any other AI-unavailable condition and fall back."""


class stream_slot:
    """Non-blocking concurrency-slot context manager.

    Usage:
        with stream_slot():
            ... make the AI call ...
    Raises StreamSlotUnavailable immediately if the process is already at
    PUBLIC_INTAKE_AI_MAX_CONCURRENT_STREAMS — never blocks a request waiting
    for a slot to free up.
    """

    def __enter__(self):
        if not _stream_semaphore.acquire(blocking=False):
            raise StreamSlotUnavailable()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        _stream_semaphore.release()
        return False


# --- Turn cap ---------------------------------------------------------------

def max_ai_turns():
    try:
        return max(1, int(os.getenv("PUBLIC_INTAKE_MAX_AI_TURNS", "8")))
    except (TypeError, ValueError):
        return 8


def assistant_turn_count(chat_history):
    return sum(1 for m in chat_history if isinstance(m, dict) and m.get("role") == "assistant")


# --- Timeout -----------------------------------------------------------------

def ai_timeout_seconds():
    try:
        return max(5.0, float(os.getenv("PUBLIC_INTAKE_AI_TIMEOUT_SECONDS", "20")))
    except (TypeError, ValueError):
        return 20.0
