# backend/app/homepage_promotion.py
#
# Control plane for the homepage promotion of the 300K Limited-Time offer.
#
# Everything an operator can change without a deploy lives in a single
# AppSetting row, so activating, extending, or ending the promotion is one
# admin PATCH and takes effect globally within one cache TTL. The marketing
# copy itself is NOT here — it lives with the modal in the frontend. This
# module decides only whether the promotion runs, where its CTA points, and
# how often a visitor may see it.
#
# Two stopping conditions, both evaluated server-side so a stale browser can
# never keep showing a finished promotion:
#   1. `active` — the operator switch.
#   2. `sales_cap` — the promotion soft-stops after this many 300K sales.
#      There is no end date today; `ends_at` exists so one can be added later
#      by writing the field, with no code change on either side.
#
# `show_deadline` / `show_remaining` are the display switches for those two
# numbers. Both are off, so the public payload carries `deadline: null` and
# `remaining: null` and the modal renders neither. Turning a switch on starts
# populating the field the modal already knows how to render.

import threading
import time
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.founder_entitlements import (
    LIMITED_TIME_300K_CREDIT_SOURCE,
    has_limited_time_300k_entitlement,
)
from app.models import AppSetting, PersistentCreditGrant

PROMOTION_SETTING_KEY = "homepage_promotion"
PROMOTION_ID = "rank_them_300k"

# The promotion soft-stops here. Sales past the cap are not blocked at
# checkout — the homepage promotion simply stops asking for them.
DEFAULT_SALES_CAP = 1002
DEFAULT_CAMPAIGN_PATH = "/limited-time/project-prioritization"

# The campaign landing pages a promotion CTA is allowed to point at. Anything
# else falls back to the default rather than sending visitors somewhere the
# offer is not explained.
ALLOWED_CAMPAIGN_PATHS = (
    "/limited-time/project-prioritization",
    "/limited-time/client-decisions",
    "/limited-time/strategic-planning",
)

# Frequency ceilings. The browser enforces these per visitor; the server owns
# the numbers so they can be retuned without a deploy.
DEFAULT_FREQUENCY = {
    "delay_seconds": 12,      # dwell time before the first appearance
    "cooldown_hours": 72,     # minimum gap between appearances
    "max_impressions": 3,     # lifetime appearances per browser
}
MAX_DELAY_SECONDS = 600
MAX_COOLDOWN_HOURS = 24 * 365
MAX_IMPRESSIONS_CEILING = 25

_CACHE_TTL_SECONDS = 30
_cache_lock = threading.Lock()
_cache = {"state": None, "checked_at": 0.0}


def _to_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _to_int(value, default, *, minimum, maximum):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _to_iso_datetime(value):
    """Accepts an ISO-8601 string (or None) and returns a normalized UTC ISO
    string. Anything unparseable is treated as 'no end date' rather than
    failing the whole config."""
    if value in (None, "", False):
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        raw = str(value).strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _resolve_ends_at(incoming, current):
    """An explicit null clears the end date; an unparseable one keeps whatever
    was already set, so a typo can never silently un-schedule the end of a
    promotion."""
    stored = _to_iso_datetime(current.get("ends_at"))
    if "ends_at" not in incoming:
        return stored
    raw = incoming.get("ends_at")
    if raw in (None, "", False):
        return None
    return _to_iso_datetime(raw) or stored


def default_promotion_config():
    return {
        "active": False,
        "campaign_path": DEFAULT_CAMPAIGN_PATH,
        "sales_cap": DEFAULT_SALES_CAP,
        "ends_at": None,
        "show_deadline": False,
        "show_remaining": False,
        "frequency": dict(DEFAULT_FREQUENCY),
    }


def normalize_promotion_config(values, base=None):
    """Merge a partial config onto `base` (defaults when omitted). Unknown keys
    are dropped and every value is coerced and clamped, so a bad admin payload
    degrades to the previous value instead of breaking the homepage."""
    current = base if isinstance(base, dict) else default_promotion_config()
    incoming = values if isinstance(values, dict) else {}

    current_path = str(current.get("campaign_path") or "").strip()
    if current_path not in ALLOWED_CAMPAIGN_PATHS:
        current_path = DEFAULT_CAMPAIGN_PATH
    campaign_path = str(incoming.get("campaign_path") or current_path).strip()
    if campaign_path not in ALLOWED_CAMPAIGN_PATHS:
        campaign_path = current_path

    current_cap = _to_int(current.get("sales_cap"), DEFAULT_SALES_CAP, minimum=0, maximum=1_000_000)
    sales_cap = (
        _to_int(incoming.get("sales_cap"), current_cap, minimum=0, maximum=1_000_000)
        if "sales_cap" in incoming
        else current_cap
    )

    current_frequency = current.get("frequency") if isinstance(current.get("frequency"), dict) else {}
    incoming_frequency = incoming.get("frequency") if isinstance(incoming.get("frequency"), dict) else {}

    def frequency_value(key, minimum, maximum):
        fallback = _to_int(
            current_frequency.get(key),
            DEFAULT_FREQUENCY[key],
            minimum=minimum,
            maximum=maximum,
        )
        if key not in incoming_frequency:
            return fallback
        return _to_int(incoming_frequency.get(key), fallback, minimum=minimum, maximum=maximum)

    return {
        "active": _to_bool(
            incoming.get("active") if "active" in incoming else current.get("active"),
            default=False,
        ),
        "campaign_path": campaign_path,
        "sales_cap": sales_cap,
        "ends_at": _resolve_ends_at(incoming, current),
        "show_deadline": _to_bool(
            incoming.get("show_deadline") if "show_deadline" in incoming else current.get("show_deadline"),
            default=False,
        ),
        "show_remaining": _to_bool(
            incoming.get("show_remaining") if "show_remaining" in incoming else current.get("show_remaining"),
            default=False,
        ),
        "frequency": {
            "delay_seconds": frequency_value("delay_seconds", 0, MAX_DELAY_SECONDS),
            "cooldown_hours": frequency_value("cooldown_hours", 0, MAX_COOLDOWN_HOURS),
            "max_impressions": frequency_value("max_impressions", 0, MAX_IMPRESSIONS_CEILING),
        },
    }


def get_promotion_config():
    """For the admin view — lets a DB error surface normally, the way every
    other admin read does."""
    row = db.session.get(AppSetting, PROMOTION_SETTING_KEY)
    stored = row.value if row and isinstance(row.value, dict) else {}
    config = normalize_promotion_config(stored)
    config["updated_at"] = row.updated_at.isoformat() if row and row.updated_at else None
    return config


def save_promotion_config(patch):
    """Applies a partial update on top of what is stored. Does not commit —
    the caller owns the transaction, matching the other admin controls."""
    row = db.session.get(AppSetting, PROMOTION_SETTING_KEY)
    stored = row.value if row and isinstance(row.value, dict) else {}
    normalized = normalize_promotion_config(patch, base=normalize_promotion_config(stored))
    if row is None:
        row = AppSetting(key=PROMOTION_SETTING_KEY, value=normalized)
        db.session.add(row)
    else:
        row.value = normalized
    return normalized


def limited_time_300k_sales_count():
    """Sales that still count against the cap. A reversed grant (refund or
    chargeback) releases its slot, so the promotion reflects live sales."""
    return int(
        PersistentCreditGrant.query
        .filter(
            PersistentCreditGrant.source == LIMITED_TIME_300K_CREDIT_SOURCE,
            PersistentCreditGrant.status != "reversed",
        )
        .count()
    )


def _now_utc():
    return datetime.now(timezone.utc)


def promotion_is_live(config, sales_count, *, now=None):
    """The single definition of 'the promotion is running'. Every stop
    condition is checked here so no caller can miss one."""
    if not isinstance(config, dict) or not config.get("active"):
        return False

    sales_cap = config.get("sales_cap")
    if isinstance(sales_cap, int) and sales_cap > 0 and int(sales_count or 0) >= sales_cap:
        return False

    ends_at = _to_iso_datetime(config.get("ends_at"))
    if ends_at is not None:
        moment = now or _now_utc()
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        if moment >= datetime.fromisoformat(ends_at):
            return False

    return True


def _read_live_state():
    row = db.session.get(AppSetting, PROMOTION_SETTING_KEY)
    config = normalize_promotion_config(row.value if row and isinstance(row.value, dict) else {})
    sales_count = limited_time_300k_sales_count() if config.get("active") else 0
    return {"config": config, "sales_count": sales_count}


def _cached_live_state():
    """Cached ~30s in-process — the homepage is the highest-traffic page in the
    app and this runs on every load. Fails CLOSED (promotion off) if the read
    itself fails, since a visitor should never be shown an offer we could not
    confirm is still running."""
    now = time.monotonic()
    with _cache_lock:
        cached = _cache
        if cached["state"] is not None and (now - cached["checked_at"]) < _CACHE_TTL_SECONDS:
            return cached["state"]
    try:
        state = _read_live_state()
    except SQLAlchemyError:
        state = {"config": default_promotion_config(), "sales_count": 0}
    with _cache_lock:
        _cache["state"] = state
        _cache["checked_at"] = now
    return state


def reset_promotion_cache():
    """Clears the in-process cache so an admin change (or a test) is visible
    immediately instead of up to one TTL later."""
    with _cache_lock:
        _cache["state"] = None
        _cache["checked_at"] = 0.0


def public_promotion_state(user=None, *, now=None):
    """What the homepage needs to decide whether to show the modal.

    Carries no marketing copy and no sales figures: `remaining` and `deadline`
    stay null until their display switches are turned on, so nothing about the
    pace of the promotion leaks to visitors today.
    """
    state = _cached_live_state()
    config = state["config"]
    sales_count = state["sales_count"]
    live = promotion_is_live(config, sales_count, now=now)

    suppressed = False
    if user is not None:
        try:
            suppressed = bool(has_limited_time_300k_entitlement(user))
        except SQLAlchemyError:
            suppressed = False

    remaining = None
    if live and config.get("show_remaining") and int(config.get("sales_cap") or 0) > 0:
        remaining = max(0, int(config["sales_cap"]) - int(sales_count))

    deadline = config.get("ends_at") if (live and config.get("show_deadline")) else None

    return {
        "id": PROMOTION_ID,
        "active": bool(live and not suppressed),
        "suppressed": suppressed,
        "suppression_reason": "purchased" if suppressed else None,
        "campaign_path": config["campaign_path"] if live else None,
        "frequency": dict(config["frequency"]) if live else None,
        "deadline": deadline,
        "remaining": remaining,
    }
