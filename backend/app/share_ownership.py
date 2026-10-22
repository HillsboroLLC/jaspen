"""Which organization owns a share link, and who may manage it.

Ownership comes from the underlying report -- the owner's UserSession row for
the link's thread -- not from the person who created the link. It is decided
once (at creation, or by the migration backfill for older links) and stored in
``shared_artifact_ownership``, so later edits to the project cannot move it.

None of this changes what a link shows or who can open it. The public token,
the link's audience and its disclosure settings are untouched; these rules
only decide who may manage a link and whether an unresolved link keeps
serving while it waits for review.
"""

from datetime import datetime

from . import db, org_access
from .models import SharedArtifactOwnership, UserSession

STATE_PERSONAL = 'personal'
STATE_ORGANIZATION = 'organization'
STATE_AMBIGUOUS = 'ambiguous'


def classify(org_ids):
    """(state, organization_id) for the organization ids of a link's report rows.

    ``None`` entries are rows with no organization. The migration that
    backfills existing links carries an identical copy of this function.
    """
    if not org_ids:
        return STATE_AMBIGUOUS, None
    distinct = set(org_ids)
    if distinct == {None}:
        return STATE_PERSONAL, None
    if len(distinct) == 1:
        return STATE_ORGANIZATION, next(iter(distinct))
    return STATE_AMBIGUOUS, None


def resolve(owner_user_id, thread_id):
    rows = (
        UserSession.query
        .with_entities(UserSession.organization_id)
        .filter(UserSession.session_id == str(thread_id))
        .filter(
            (UserSession.user_id == str(owner_user_id))
            | (UserSession.created_by_user_id == str(owner_user_id))
        )
        .all()
    )
    return classify([org_id or None for (org_id,) in rows])


def record_for_new_link(link):
    """Store ownership for a link being created (same transaction as the link)."""
    if link.id is None:
        db.session.flush()
    state, org_id = resolve(link.owner_user_id, link.thread_id)
    row = SharedArtifactOwnership(
        shared_artifact_id=link.id,
        state=state,
        organization_id=org_id,
        source='created',
        resolved_at=datetime.utcnow(),
    )
    db.session.add(row)
    return row


def ownership_for(link):
    """(state, organization_id). Links with no stored row resolve on the fly."""
    row = db.session.get(SharedArtifactOwnership, link.id)
    if row is not None:
        return row.state, row.organization_id
    return resolve(link.owner_user_id, link.thread_id)


def owner_may_manage(link, user, *, path):
    """May the link's creator still list, edit or turn off this link?

    Personal links: always. Organization links: only while the creator is an
    active member; afterwards the organization's owners and admins manage it.
    Ambiguous links: held for review.
    """
    state, org_id = ownership_for(link)
    if state == STATE_PERSONAL:
        return True
    if state == STATE_ORGANIZATION:
        return org_access.allow(
            org_id, user.id, path=path, resource_type='share_link', resource_id=link.id,
        )
    return _held(link, path=path, user_id=user.id)


def serves_publicly(link):
    """False only for an ambiguous link while enforcing (held for review)."""
    state, _org_id = ownership_for(link)
    if state != STATE_AMBIGUOUS:
        return True
    return _held(link, path='share_public_view', user_id=None)


def _held(link, *, path, user_id):
    mode = org_access.enforcement_mode()
    if mode == org_access.MODE_OFF:
        return True
    org_access.record(
        mode=mode,
        path=path,
        resource_type='share_link',
        resource_id=link.id,
        organization_id=None,
        user_id=user_id or link.owner_user_id,
        reason='ambiguous_ownership',
    )
    return mode != org_access.MODE_ENFORCE
