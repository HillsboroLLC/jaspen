"""Authorized project context shared by every Jaspen assistant entrance.

The route remains responsible for resolving access before generation.  This
module turns that authorized result into one small, read-only contract for the
main conversation and the workspace assistants.  It never falls back to a
user-scoped project lookup and never changes prompt text.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Sequence

from .models import User
from .session_access import SessionNotFound, can_write_session, resolve_session_for_actor


def _project_session(sessions, project_id):
    if not isinstance(sessions, Mapping):
        return None
    direct = sessions.get(project_id)
    if isinstance(direct, dict):
        return direct
    for candidate in sessions.values():
        if (
            isinstance(candidate, dict)
            and str(candidate.get("session_id") or "").strip() == project_id
        ):
            return candidate
    return None


def _project_scenarios(scenarios, project_id):
    if not isinstance(scenarios, Mapping):
        return {}
    direct = scenarios.get(project_id)
    return direct if isinstance(direct, dict) else {}


def _history(session):
    if not isinstance(session, dict):
        return []
    history = session.get("chat_history")
    if isinstance(history, list):
        return history
    result = session.get("result")
    if isinstance(result, dict) and isinstance(result.get("chat_history"), list):
        return result["chat_history"]
    return []


@dataclass(frozen=True)
class SharedAssistantContext:
    """One authorized project's context at an assistant-entry boundary."""

    project_id: str
    organization_id: str | None
    actor_user_id: str
    role: str | None
    can_write: bool
    revision: int | None
    session: dict
    project_data: dict
    history: Sequence[dict]
    view_context: Mapping[str, Any]

    @property
    def scorecard_result(self):
        result = self.session.get("result")
        return result if isinstance(result, dict) else {}

    @property
    def execution_plan(self):
        plan = self.project_data.get("project_wbs")
        # ``None`` is the optimistic-save sentinel for a project that has no
        # plan yet.  Do not collapse it to an empty mapping: the first edit
        # must compare absent-to-absent before creating the plan.
        return plan if isinstance(plan, dict) else None

    def recent_history(self, *, limit, max_chars):
        """Return the existing prompt shape for a bounded history excerpt."""
        excerpt = []
        for item in list(self.history)[-int(limit):]:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip() or "user"
            content = str(item.get("content") or item.get("text") or "").strip()
            if content:
                excerpt.append({"role": role, "content": content[:int(max_chars)]})
        return excerpt


def build_shared_assistant_context(
    user,
    thread_id,
    *,
    sessions,
    project_row=None,
    project=None,
    scenarios=None,
    session=None,
    history=None,
    view_context=None,
    require_write=False,
):
    """Build context only after proving the actor may use this exact project.

    ``project`` is the already-authorized ``TurnProject`` used by the main
    conversation.  Workspace routes pass their authorized canonical row.
    Both paths are checked against the same project id and organization; a
    mismatch fails closed instead of borrowing data from another project.
    """
    if user is not None and not isinstance(user, User):
        user = User.query.get(str(user))
    project_id = str(thread_id or "").strip()
    if user is None or not project_id:
        raise SessionNotFound()

    role = None
    revision = None
    can_write = False
    row = project_row

    if project is not None:
        if not project.matches(project_id) or not project.can_read:
            raise SessionNotFound(denied=True)
        if str(project.actor_user_id or "") != str(user.id):
            raise SessionNotFound(denied=True)
        if require_write and not project.can_write:
            # Re-run the authoritative access seam to preserve its approved
            # 403 response rather than inventing another permission error.
            resolve_session_for_actor(user, project_id, require_write=True)
        # The turn already bound and authorized this row before reserving.
        # Re-resolving it here would make prompt assembly sensitive to commits
        # made by the capture step within the same turn.  Existing prompt
        # readers still call ``project.row()`` when they load project data, so
        # membership loss continues to fail closed at the actual read.
        if row is not None:
            authorized_project_row = project.row()
            if (
                authorized_project_row is None
                or str(row.id) != str(authorized_project_row.id)
            ):
                raise SessionNotFound(denied=True)
        organization_id = project.organization_id
        role = project.role
        revision = project.revision
        can_write = bool(project.can_write)
    else:
        authorized_row, membership = resolve_session_for_actor(
            user, project_id, require_write=require_write,
        )
        if row is not None and str(row.id) != str(authorized_row.id):
            raise SessionNotFound(denied=True)
        row = authorized_row
        organization_id = row.organization_id
        role = getattr(membership, "role", None) if membership is not None else None
        revision = int(row.revision or 1)
        can_write = can_write_session(row, user, membership=membership)

    if row is not None:
        if str(row.session_id or "").strip() != project_id:
            raise SessionNotFound(denied=True)
        row_org = str(row.organization_id) if row.organization_id is not None else None
        context_org = str(organization_id) if organization_id is not None else None
        if row_org != context_org:
            raise SessionNotFound(denied=True)

    resolved_session = session if isinstance(session, dict) else _project_session(sessions, project_id)
    if resolved_session is None:
        resolved_session = {}
    stored_id = str(resolved_session.get("session_id") or "").strip()
    if stored_id and stored_id != project_id:
        raise SessionNotFound(denied=True)

    project_data = _project_scenarios(scenarios, project_id)
    resolved_history = history if isinstance(history, list) else _history(resolved_session)
    return SharedAssistantContext(
        project_id=project_id,
        organization_id=str(organization_id) if organization_id is not None else None,
        actor_user_id=str(user.id),
        role=str(role) if role is not None else None,
        can_write=bool(can_write),
        revision=revision,
        session=resolved_session,
        project_data=project_data,
        history=resolved_history,
        view_context=view_context if isinstance(view_context, dict) else {},
    )
