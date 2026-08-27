# backend/app/session_access.py
#
# Canonical organization ownership for UserSession rows, and the single place
# where read/write access to a session is decided.
#
# The model this file implements
# -----------------------------
#   organization_id  -- CANONICAL OWNER of the durable work product.
#   user_id          -- attribution: the row's original/home contributor.
#   created_by_user_id -- attribution: who created it. Never reassigned.
#   last_edited_by_user_id -- attribution: who last accepted a write.
#
# Ownership is organization-based for every account, not only Team+. Every user
# already owns a solo organization (app.orgs.ensure_default_organization_for_user),
# so a single universal ownership path serves solo users and teams alike and no
# plan branch belongs in this file. The plan gate lives at INVITE time
# (orgs.plan_allows_collaboration), which is why a sub-Team org can never hold a
# second member and the predicates below collapse to "it's mine" for solo users.
#
# Why there is no UNIQUE(organization_id, session_id)
# ---------------------------------------------------
# Two rows can legitimately share (organization_id, session_id):
#   1. PERSONAL_SESSION_IDS -- the `__user_memory__` sentinel is stored as a
#      UserSession row per user. Every member of an org has one with the same
#      session_id, so a unique constraint would be unsatisfiable.
#   2. Historical collaborator forks created before this phase.
# Canonicity is therefore resolved here, deterministically: OLDEST created_at
# wins, because the original always predates the fork.

from datetime import datetime

from app import db
from app.models import Organization, OrganizationMember, UserSession
from app.orgs import (
    active_membership_for_user,
    can_edit_projects,
    can_manage_org,
    normalize_org_role,
)


# --- Personal-scope sessions -------------------------------------------------
#
# Rows whose session_id appears here are personal state that happens to live in
# `user_sessions`. They are never organization-owned, never resolved across
# members, and never carry a server-derived organization_id. `__user_memory__`
# is the cross-session memory sentinel written by
# app.routes.ai_agent._save_user_memory; converting it into shared state is a
# dedicated later phase with its own permission and provenance design, NOT a
# side effect of this migration.
PERSONAL_SESSION_IDS = frozenset({'__user_memory__'})

VISIBILITY_PRIVATE = 'private'
VISIBILITY_TEAM = 'team'
VISIBILITY_SPECIFIC = 'specific'


def is_personal_session_id(session_id):
    """True for rows that must stay outside canonical organization ownership."""
    return str(session_id or '').strip() in PERSONAL_SESSION_IDS


# --- Errors ------------------------------------------------------------------

class SessionAccessError(Exception):
    """Raised when a caller may not touch a session. Carries an HTTP shape."""

    def __init__(self, status, code, message):
        super().__init__(message)
        self.status = int(status)
        self.code = str(code)
        self.message = str(message)

    def to_response(self):
        return {'error': self.message, 'code': self.code}, self.status


class SessionNotFound(SessionAccessError):
    def __init__(self, message='Session not found'):
        super().__init__(404, 'not_found', message)


class SessionForbidden(SessionAccessError):
    def __init__(self, message='You do not have access to this project'):
        super().__init__(403, 'forbidden', message)


class RevisionConflict(SessionAccessError):
    """The caller's write was based on a revision that is no longer current.

    Carries both revisions so the client can tell the user what happened and
    reload without guessing. Never resolved by overwriting.
    """

    def __init__(self, expected_revision, current_revision, session_id=None):
        super().__init__(
            409,
            'revision_conflict',
            'This project was changed by someone else since you opened it. '
            'Reload to get the latest version before saving again.',
        )
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        self.session_id = session_id

    def to_response(self):
        body, status = super().to_response()
        body.update({
            'expected_revision': self.expected_revision,
            'current_revision': self.current_revision,
            'session_id': self.session_id,
        })
        return body, status


# --- Organization context ----------------------------------------------------

def active_org_id_for_user(user):
    """The org that owns work this user creates right now.

    Deliberately does NOT call resolve_active_org_for_user(), which commits.
    Read paths must not write.
    """
    if user is None:
        return None
    return getattr(user, 'active_organization_id', None) or None


def org_is_multi_member(organization_id):
    """True when more than one active member can reach this org's work."""
    if not organization_id:
        return False
    return (
        OrganizationMember.query
        .filter_by(organization_id=str(organization_id), status='active')
        .limit(2)
        .count()
    ) > 1


# --- Canonical resolution ----------------------------------------------------

def canonical_row(user, session_id, *, include_archived=False):
    """The one durable row for (this user's org, session_id).

    Resolution order:
      1. Personal-scope ids resolve to the caller's own row and stop.
      2. The organization-owned row, oldest created_at first, so a historical
         fork can never displace the original.
      3. The caller's own row, for work that predates an org binding.

    Returns the row or None. Performs NO authorization -- callers must use
    resolve_session_for_actor().
    """
    sid = str(session_id or '').strip()
    if not sid or user is None:
        return None

    def _visible(query):
        if not include_archived:
            query = query.filter(UserSession.archived_at.is_(None))
        return query

    own = _visible(
        UserSession.query.filter_by(user_id=str(user.id), session_id=sid)
    ).first()

    if is_personal_session_id(sid):
        return own

    org_id = active_org_id_for_user(user)
    if org_id:
        row = _visible(
            UserSession.query.filter_by(organization_id=str(org_id), session_id=sid)
        ).order_by(
            UserSession.created_at.asc(), UserSession.id.asc()
        ).first()
        if row is not None:
            return row

    return own


# --- Predicates --------------------------------------------------------------

def _shared_ids(row):
    raw = row.shared_with_user_ids if isinstance(row.shared_with_user_ids, list) else []
    return {str(item or '').strip() for item in raw if str(item or '').strip()}


def is_attributed_to(row, user_id):
    """True when this user created the row or is its home contributor."""
    uid = str(user_id)
    return uid in {
        str(row.created_by_user_id or ''),
        str(row.user_id or ''),
    }


def can_read_session(row, user, membership=None):
    """Read access. Mirrors routes/team.py::_can_access_project exactly, with
    org membership required first so a stale organization_id cannot leak a row
    to someone who has since been removed from the organization."""
    if not isinstance(row, UserSession) or user is None:
        return False

    uid = str(user.id)
    if is_attributed_to(row, uid):
        return True

    if is_personal_session_id(row.session_id):
        return False

    if not row.organization_id:
        return False
    if membership is None:
        membership = active_membership_for_user(row.organization_id, uid)
    if membership is None:
        return False

    visibility = str(row.visibility or VISIBILITY_PRIVATE).strip().lower()
    if visibility == VISIBILITY_TEAM:
        return True
    if visibility == VISIBILITY_SPECIFIC:
        return uid in _shared_ids(row)
    return False


def can_write_session(row, user, membership=None):
    """Write access: read access AND an editing role. Viewers never write."""
    if not can_read_session(row, user, membership=membership):
        return False

    uid = str(user.id)
    if is_personal_session_id(row.session_id):
        return is_attributed_to(row, uid)

    if membership is None and row.organization_id:
        membership = active_membership_for_user(row.organization_id, uid)

    if membership is not None:
        # A viewer is read-only even on work they created; the seat is the
        # entitlement, not the authorship.
        return can_edit_projects(normalize_org_role(membership.role))

    # No org binding at all -- legacy personal row. Attribution is the gate.
    return is_attributed_to(row, uid)


def can_archive_session(row, user, membership=None):
    """Authority to destroy the ORGANIZATION's canonical row -- archive it,
    schedule its purge, or delete it permanently.

    This is the single destructive-authority predicate. Everything that can
    destroy organizational work routes through it: the per-project delete, the
    bulk hard reset, the permanent purge, and the purge sweep. There is
    deliberately no second permission system.

    The rule, in order:

      * Personal-scope rows and rows with no organization -- attribution.
      * A solo organization -- attribution. The only member IS the owner, so
        this is what keeps individual behaviour exactly as it was.
      * A multi-member organization:
          - owner/admin may destroy anything in the org;
          - otherwise the row's visibility decides. PRIVATE work is still the
            author's own, but once work is SHARED, being the person who
            happened to create it confers NO destructive authority. It is the
            organization's now, and other members depend on it.

    That last clause is the Phase 2 correction. Creator status used to grant
    hard-delete over shared work, which contradicted the per-project rule and
    let one member destroy institutional work through a bulk reset.
    """
    if not can_read_session(row, user, membership=membership):
        return False

    uid = str(user.id)
    if is_personal_session_id(row.session_id) or not row.organization_id:
        return is_attributed_to(row, uid)

    if not org_is_multi_member(row.organization_id):
        return is_attributed_to(row, uid)

    if membership is None:
        membership = active_membership_for_user(row.organization_id, uid)
    if membership is not None and can_manage_org(normalize_org_role(membership.role)):
        return True

    visibility = str(row.visibility or VISIBILITY_PRIVATE).strip().lower()
    if visibility == VISIBILITY_PRIVATE:
        return is_attributed_to(row, uid)
    return False


# --- The chokepoint ----------------------------------------------------------

def resolve_session_for_actor(user, session_id, *, require_write=False,
                              include_archived=False):
    """Resolve the canonical row and authorize BEFORE returning it.

    Authorization is evaluated here, ahead of any context assembly, so no
    caller can build a prompt or a response out of a row it may not read.

    Returns (row, membership). Raises SessionNotFound / SessionForbidden.
    """
    row = canonical_row(user, session_id, include_archived=include_archived)
    if row is None:
        raise SessionNotFound()

    membership = None
    if row.organization_id and not is_personal_session_id(row.session_id):
        membership = active_membership_for_user(row.organization_id, str(user.id))

    if not can_read_session(row, user, membership=membership):
        # 404 rather than 403 for a row the caller cannot read at all: a
        # non-member must not be able to probe which session ids exist.
        raise SessionNotFound()

    if require_write and not can_write_session(row, user, membership=membership):
        raise SessionForbidden(
            'Your role on this project is read-only.'
        )

    return row, membership


# --- Optimistic concurrency --------------------------------------------------

def revision_required_for(row):
    """True when a write MUST declare the revision it is based on.

    Required exactly where two people can collide: an organization-owned row
    that has been shared beyond its creator, in an org with more than one
    active member. Private work -- which is every solo user and every unshared
    project -- stays optional, so no existing individual client can break.
    """
    if not isinstance(row, UserSession):
        return False
    if is_personal_session_id(row.session_id):
        return False
    visibility = str(row.visibility or VISIBILITY_PRIVATE).strip().lower()
    if visibility == VISIBILITY_PRIVATE:
        return False
    return org_is_multi_member(row.organization_id)


def check_revision(row, base_revision):
    """Validate a caller's base revision against the stored one.

    `base_revision` may be None when the row does not require it. A mismatch is
    always a conflict -- never a silent overwrite.
    """
    if not isinstance(row, UserSession):
        return

    current = int(row.revision or 1)

    if base_revision is None or str(base_revision).strip() == '':
        if revision_required_for(row):
            raise RevisionConflict(None, current, session_id=row.session_id)
        return

    try:
        expected = int(base_revision)
    except (TypeError, ValueError):
        raise RevisionConflict(base_revision, current, session_id=row.session_id)

    if expected != current:
        raise RevisionConflict(expected, current, session_id=row.session_id)


def stamp_write(row, user_id):
    """Record an accepted mutation: bump revision, stamp the editor.

    Called once per accepted write, after check_revision() has passed.
    """
    row.revision = int(row.revision or 1) + 1
    if user_id:
        row.last_edited_by_user_id = str(user_id)
    return row.revision


def extract_base_revision(payload):
    """Pull the caller's base revision out of a request body.

    Reads `base_revision` ONLY, deliberately -- not `revision`. Server-side
    flows routinely load a session once and save it several times within one
    request; every payload they carry echoes the `revision` field the loader
    put there, so treating that as an assertion would make the second save in
    any such flow conflict with the first. `base_revision` is an explicit
    claim by a client that it is writing on top of a specific version.

    Absence is not a bypass: check_revision() still refuses a write to a row
    where revision_required_for() is true.
    """
    if not isinstance(payload, dict):
        return None
    value = payload.get('base_revision')
    return value if value is not None else None


# --- Personal view state -----------------------------------------------------

def hidden_ids(row):
    raw = row.hidden_for_user_ids if isinstance(row.hidden_for_user_ids, list) else []
    return [str(item or '').strip() for item in raw if str(item or '').strip()]


def is_hidden_for(row, user_id):
    return str(user_id) in set(hidden_ids(row))


def hide_for_user(row, user_id):
    """Remove a shared project from ONE member's history.

    Never touches archived_at/purge_after, so the purge sweep can never destroy
    organization-owned work because one member tidied their own list.
    """
    current = hidden_ids(row)
    uid = str(user_id)
    if uid not in current:
        current.append(uid)
    row.hidden_for_user_ids = current
    return row


def unhide_for_user(row, user_id):
    uid = str(user_id)
    row.hidden_for_user_ids = [item for item in hidden_ids(row) if item != uid]
    return row


def uses_personal_hide(row, user):
    """True when 'delete from my history' must hide rather than archive.

    The rule is entitlement, not intent: someone who may archive the
    organization's work does so, and everyone else only hides it for
    themselves. That gives both halves of the requirement at once --

      * a collaborator or viewer can never schedule a purge of shared work
        merely by tidying their own list, and
      * an owner/admin/creator retains a working archive, so solo users keep
        today's behaviour byte-for-byte (a solo org has one member, who is its
        owner, so this always returns False for them).

    A later phase can add an explicit scope argument if an owner wants to hide
    without archiving; Phase 1 deliberately does not invent that control.
    """
    if not isinstance(row, UserSession) or user is None:
        return False
    if is_personal_session_id(row.session_id) or not row.organization_id:
        return False
    if not org_is_multi_member(row.organization_id):
        # Solo organization: removing it from your history IS removing it from
        # the organization's history. Today's behaviour, unchanged.
        return False

    # Derived from the destructive-authority predicate rather than restating
    # it. Phase 1 spelled the rule out twice and the two copies disagreed --
    # the per-project path protected shared work while the bulk reset did not.
    # Anyone without authority to destroy the organization's copy gets a
    # personal hide instead.
    return not can_archive_session(row, user)


# --- Duplicate (fork) detection ---------------------------------------------

def find_forked_sessions(organization_id=None):
    """Rows sharing (organization_id, session_id) -- historical fork damage.

    Personal-scope ids are excluded: multiple `__user_memory__` rows per org are
    correct, not duplicates. Returns [{organization_id, session_id, count,
    row_ids, canonical_row_id}] with the canonical (oldest) row named so a
    reconciliation is deterministic and reviewable rather than guessed.
    """
    query = (
        db.session.query(
            UserSession.organization_id,
            UserSession.session_id,
            db.func.count(UserSession.id).label('n'),
        )
        .filter(UserSession.organization_id.isnot(None))
        .filter(~UserSession.session_id.in_(tuple(PERSONAL_SESSION_IDS)))
        .group_by(UserSession.organization_id, UserSession.session_id)
        .having(db.func.count(UserSession.id) > 1)
    )
    if organization_id:
        query = query.filter(UserSession.organization_id == str(organization_id))

    out = []
    for org_id, sid, count in query.all():
        rows = (
            UserSession.query
            .filter_by(organization_id=org_id, session_id=sid)
            .order_by(UserSession.created_at.asc(), UserSession.id.asc())
            .all()
        )
        out.append({
            'organization_id': org_id,
            'session_id': sid,
            'count': int(count),
            'row_ids': [r.id for r in rows],
            'canonical_row_id': rows[0].id if rows else None,
            'contributor_user_ids': [r.user_id for r in rows],
        })
    return out
