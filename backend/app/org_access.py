# backend/app/org_access.py
#
# Organization membership gate for attributed work.
#
# The rule
# --------
# Organization-owned work (any row with an organization_id) is reachable only
# by ACTIVE members of that organization. Being the row's creator or home
# contributor no longer grants access on its own: a member who is removed, or
# whose seat is revoked, loses access to the organization's work even though
# their user id is still stamped on it. Personal rows (no organization, or a
# personal-scope session id) are unaffected.
#
# Rollout
# -------
# ORG_ACCESS_ENFORCEMENT selects the mode:
#   report  (default) -- legacy behavior; every access the rule WOULD refuse
#                        is recorded in org_access_shadow_events for review.
#   enforce           -- the rule refuses access.
#   off               -- emergency rollback: legacy behavior, nothing recorded.
#
# Report mode is temporary (approved for roughly 48-72 hours) while the
# recorded events are reviewed; then the flag moves to enforce.

import logging
import os
import threading
import time
from datetime import datetime, timedelta

from flask import has_app_context, has_request_context, request

logger = logging.getLogger(__name__)

MODE_REPORT = 'report'
MODE_ENFORCE = 'enforce'
MODE_OFF = 'off'
MODES = (MODE_REPORT, MODE_ENFORCE, MODE_OFF)

# The same (user, resource, path) is recorded at most once per window, so a
# history list loaded on every page view cannot flood the table.
_DEDUP_WINDOW_SECONDS = 3600
_DEDUP_MAX_KEYS = 5000
_recent = {}
_recent_lock = threading.Lock()

# Events are kept for review, not forever. Older rows are pruned at most once
# per hour per process, on the same connection that records a new event.
RETENTION_DAYS = 90
_PRUNE_INTERVAL_SECONDS = 3600
_last_prune = [0.0]


def enforcement_mode():
    raw = str(os.environ.get('ORG_ACCESS_ENFORCEMENT') or '').strip().lower()
    if raw in MODES:
        return raw
    if raw:
        logger.warning('ORG_ACCESS_ENFORCEMENT=%r is not a known mode; using report', raw)
    return MODE_REPORT


def active_org_ids(user_id):
    """Organization ids where this user holds an active membership.

    Cached per request: history lists check every row against the same set.
    """
    from app.models import OrganizationMember

    uid = str(user_id or '').strip()
    if not uid:
        return frozenset()
    cache = None
    if has_request_context():
        # On the request object, not flask.g: g lives as long as the app
        # context, which can outlast a single request.
        current = request._get_current_object()
        cache = getattr(current, '_org_access_active_orgs', None)
        if cache is None:
            cache = {}
            current._org_access_active_orgs = cache
        if uid in cache:
            return cache[uid]
    ids = frozenset(
        str(org_id) for (org_id,) in
        OrganizationMember.query
        .with_entities(OrganizationMember.organization_id)
        .filter_by(user_id=uid, status='active')
        .all()
    )
    if cache is not None:
        cache[uid] = ids
    return ids


def is_member(organization_id, user_id):
    if not organization_id:
        return True
    return str(organization_id) in active_org_ids(user_id)


def allow(organization_id, user_id, *, path, resource_type, resource_id=None):
    """True when attributed access to organization work may proceed.

    Call this only where access would otherwise be granted by attribution
    (the caller created the row or is its home contributor). Personal rows
    pass; members pass; everyone else is refused in enforce mode and recorded
    in report mode.
    """
    if not organization_id or is_member(organization_id, user_id):
        return True
    mode = enforcement_mode()
    if mode == MODE_OFF:
        return True
    record(
        mode=mode,
        path=path,
        resource_type=resource_type,
        resource_id=resource_id,
        organization_id=organization_id,
        user_id=user_id,
        reason='not_active_member',
    )
    return mode != MODE_ENFORCE


def gate_row(row, user_id, *, path, resource_type=None):
    """Return the row when the caller may reach it through attribution, else None."""
    if row is None:
        return None
    rtype = resource_type or getattr(row, '__tablename__', 'row')
    rid = getattr(row, 'session_id', None) or getattr(row, 'id', None)
    if allow(getattr(row, 'organization_id', None), user_id, path=path,
             resource_type=rtype, resource_id=rid):
        return row
    return None


def gate_rows(rows, user_id, *, path, resource_type=None):
    return [
        row for row in rows
        if gate_row(row, user_id, path=path, resource_type=resource_type) is not None
    ]


def _first_seen(key):
    now = time.monotonic()
    with _recent_lock:
        seen = _recent.get(key)
        if seen is not None and now - seen < _DEDUP_WINDOW_SECONDS:
            return False
        if len(_recent) >= _DEDUP_MAX_KEYS:
            _recent.clear()
        _recent[key] = now
    return True


def reset_dedup():
    """Tests only."""
    with _recent_lock:
        _recent.clear()
        _last_prune[0] = 0.0


def _prune_due():
    now = time.monotonic()
    with _recent_lock:
        if _last_prune[0] and now - _last_prune[0] < _PRUNE_INTERVAL_SECONDS:
            return False
        _last_prune[0] = now
    return True


def record(*, mode, path, resource_type, resource_id, organization_id, user_id, reason):
    """Record one refused (enforce) or would-be-refused (report) access.

    Written on its own connection so read paths never commit the request's
    session. A failure to record is logged and never affects the request.
    """
    key = (str(user_id), str(resource_type), str(resource_id), str(path), str(reason))
    if not _first_seen(key):
        return
    logger.warning(
        'org_access %s: path=%s %s=%s org=%s user=%s reason=%s',
        'denied' if mode == MODE_ENFORCE else 'would_deny',
        path, resource_type, resource_id, organization_id, user_id, reason,
    )
    if not has_app_context():
        return
    try:
        from app import db
        from app.models import OrgAccessShadowEvent

        table = OrgAccessShadowEvent.__table__
        with db.engine.begin() as connection:
            if connection.dialect.name == 'sqlite':
                # SQLite locks the whole file; never stall a request behind
                # its own open transaction.
                connection.exec_driver_sql('PRAGMA busy_timeout = 200')
            connection.execute(table.insert().values(
                created_at=datetime.utcnow(),
                mode=str(mode)[:16],
                path=str(path)[:120],
                resource_type=str(resource_type)[:64],
                resource_id=str(resource_id)[:255] if resource_id is not None else None,
                organization_id=str(organization_id)[:36] if organization_id else None,
                user_id=str(user_id)[:36] if user_id else None,
                reason=str(reason)[:64],
            ))
            if _prune_due():
                connection.execute(table.delete().where(
                    table.c.created_at < datetime.utcnow() - timedelta(days=RETENTION_DAYS)
                ))
    except Exception:  # noqa: BLE001 -- recording must never break a request
        logger.warning('org_access: could not record shadow event', exc_info=True)
