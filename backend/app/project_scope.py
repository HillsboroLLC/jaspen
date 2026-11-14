"""One project per request, resolved through the project access seam.

Routes that act on a single project (``<thread_id>``) authorize it here, then
read its content from the organization's canonical row. A teammate therefore
sees the same project the owner sees, a read-only member is refused writes,
and a member of another organization is told the project does not exist.

Authorization itself lives in ``session_access`` and is not repeated here.
"""

import copy

from app.models import User
from app.scenarios_store import ScenariosData, load_scenarios_data
from app.session_access import (
    SessionNotFound,
    can_read_session,
    canonical_row,
    is_hidden_for,
    is_personal_session_id,
    resolve_session_for_actor,
)


def authorized_thread_scope(user_id, thread_id, *, require_write=False,
                            include_archived=False, allow_missing=False):
    """Authorize this caller for one thread, then return its working set.

    Returns ``(user, sessions, row)``. Authorization runs BEFORE the sessions
    dict is assembled, so no handler downstream can build a response or a
    prompt out of a row the caller may not read.

    The returned dict is the caller's own sessions plus the organization's
    canonical row for this thread, which keeps the existing
    ``_resolve_user_session(sessions, thread_id)`` idiom working unchanged.

    Raises SessionAccessError; the app-level handler renders it as
    404 / 403 / 409 with a machine-readable ``code``.
    """
    from app.routes.sessions import load_sessions_for_thread

    user = User.query.get(str(user_id))
    if user is None:
        raise SessionNotFound()
    try:
        row, _membership = resolve_session_for_actor(
            user, thread_id, require_write=require_write, include_archived=include_archived
        )
    except SessionNotFound as exc:
        # allow_missing preserves endpoints that can still answer for a thread
        # with no session row (e.g. usage assembled from UsageEvent rows).
        # A FORBIDDEN or unreadable row is never softened -- only a genuinely
        # absent one.
        if not allow_missing or exc.denied:
            raise
        row = None
    sessions = load_sessions_for_thread(user, thread_id, include_archived=include_archived)
    return user, sessions, row


def readable_project_row(user, thread_id, *, include_archived=False):
    """The canonical row for this thread when this member may read it, else None.

    Performs the same checks as ``load_sessions_for_thread`` so the session and
    scenario halves of one project can never come from different rows.
    """
    if user is not None and not isinstance(user, User):
        user = User.query.get(str(user))
    sid = str(thread_id or '').strip()
    if user is None or not sid:
        return None
    row = canonical_row(user, sid, include_archived=include_archived)
    if row is None or is_hidden_for(row, str(user.id)) or not can_read_session(row, user):
        return None
    return row


def project_scenarios_into(out, row):
    """Add one canonical row's scorecard and plan data to ``out``.

    Same shape and bookkeeping as ``scenarios_store.load_scenarios_data``, so a
    later project-scoped save applies only the request's change to this row.
    """
    data = row.scenarios_json if isinstance(row.scenarios_json, dict) else None
    if not data:
        return out
    db_sid = str(row.session_id)
    out[db_sid] = copy.deepcopy(data)
    out.remember(db_sid, row)
    row_payload = row.payload if isinstance(row.payload, dict) else {}
    payload_sid = str(row_payload.get('session_id') or '').strip()
    if payload_sid and payload_sid != db_sid:
        out[payload_sid] = out[db_sid]
        out.remember(payload_sid, row)
    return out


def project_scenarios(row):
    """Scorecard and plan data for exactly one canonical row."""
    out = ScenariosData()
    if row is None:
        return out
    return project_scenarios_into(out, row)


def scenarios_for_thread(user, thread_id):
    """The caller's scenario data, with this thread taken from its canonical row.

    The scenario counterpart of ``load_sessions_for_thread``: the caller's own
    entries stay (legacy lookups rely on them), and the thread's entry is the
    organization's project, never a copy the caller holds under the same id.
    When the caller may not read the thread's project, its entry is absent.
    """
    if user is not None and not isinstance(user, User):
        user = User.query.get(str(user))
    if user is None:
        return ScenariosData()
    out = load_scenarios_data(str(user.id))
    sid = str(thread_id or '').strip()
    if not sid or is_personal_session_id(sid):
        return out
    if canonical_row(user, sid, include_archived=True) is None:
        # No project under this id: nothing of the caller's stands for it.
        return out
    row = readable_project_row(user, sid, include_archived=True)
    # The canonical row is the project. Anything the caller holds under the
    # same id (a historical fork) is never authoritative for it, and when the
    # caller may not read the project, nothing is returned for it at all.
    _forget(out, sid)
    if row is not None:
        payload_sid = str((row.payload or {}).get('session_id') or '').strip() if isinstance(row.payload, dict) else ''
        if payload_sid and payload_sid != sid:
            _forget(out, payload_sid)
        project_scenarios_into(out, row)
    return out


def _forget(out, key):
    out.pop(key, None)
    for book in (out.row_ids, out.revisions, out.canonical_ids, out.originals):
        book.pop(key, None)
