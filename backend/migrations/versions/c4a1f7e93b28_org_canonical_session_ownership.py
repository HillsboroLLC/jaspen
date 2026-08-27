"""Canonical organization ownership for user_sessions (Phase 1).

Additive only. Adds the columns that let `organization_id` act as the canonical
owner while `user_id` / `created_by_user_id` stay attribution:

  * revision                -- server-owned optimistic concurrency token.
                               `updated_at` cannot be used: it is derived from
                               the CLIENT-supplied `timestamp` in
                               _normalize_session_payload().
  * last_edited_by_user_id  -- who last wrote, without touching authorship.
  * hidden_for_user_ids     -- per-member "removed from my history" state, so
                               one member cannot archive or schedule a purge of
                               organization-owned work.
  * ix_user_sessions_org_session -- canonical lookup path.

Deliberately NOT added: UNIQUE(organization_id, session_id).

Two things make that constraint unsatisfiable today:

  1. The `__user_memory__` sentinel is stored as a user_sessions row per user.
     Every member of an organization has one with that identical session_id.
  2. Historical collaborator forks may already have produced duplicate
     (organization_id, session_id) pairs.

Canonicity is therefore resolved in app/session_access.py (oldest created_at
wins). This migration REPORTS duplicates rather than resolving them: silently
picking a winner would discard someone's work. `find_forked_sessions()` names
the canonical row for each collision so a reconciliation can be reviewed and
applied deliberately in a later phase.

Revision ID: c4a1f7e93b28
Revises: b7e2d91a4c03
Create Date: 2026-08-27
"""
import logging

import sqlalchemy as sa
from alembic import op


revision = 'c4a1f7e93b28'
down_revision = 'b7e2d91a4c03'
branch_labels = None
depends_on = None

logger = logging.getLogger('alembic.runtime.migration')

PERSONAL_SESSION_IDS = ('__user_memory__',)


def _existing_columns(bind, table):
    return {col['name'] for col in sa.inspect(bind).get_columns(table)}


def _existing_indexes(bind, table):
    return {idx['name'] for idx in sa.inspect(bind).get_indexes(table)}


def _report_forked_sessions(bind):
    """Log pre-existing (organization_id, session_id) collisions.

    Never mutates. A duplicate here is real collaborator work that forked under
    the old ownership model; discarding either side without review would be
    data loss, so this surfaces them and leaves the decision to a human.
    """
    personal = ', '.join(f"'{sid}'" for sid in PERSONAL_SESSION_IDS)
    rows = bind.execute(sa.text(f"""
        SELECT organization_id, session_id, COUNT(*) AS n
        FROM user_sessions
        WHERE organization_id IS NOT NULL
          AND session_id NOT IN ({personal})
        GROUP BY organization_id, session_id
        HAVING COUNT(*) > 1
    """)).fetchall()

    if not rows:
        logger.info('[org-ownership] no forked (organization_id, session_id) rows found')
        return

    logger.warning(
        '[org-ownership] %d forked (organization_id, session_id) group(s) detected. '
        'No data was changed. The oldest row in each group is canonical; review '
        'with app.session_access.find_forked_sessions() before enforcing '
        'uniqueness in a later phase.',
        len(rows),
    )
    for org_id, session_id, count in rows[:50]:
        logger.warning(
            '[org-ownership]   org=%s session=%s rows=%s', org_id, session_id, count
        )


def upgrade():
    bind = op.get_bind()
    columns = _existing_columns(bind, 'user_sessions')
    indexes = _existing_indexes(bind, 'user_sessions')

    with op.batch_alter_table('user_sessions') as batch:
        if 'revision' not in columns:
            # server_default so the backfill of existing rows is atomic with the
            # DDL; the model default keeps new rows at 1 as well.
            batch.add_column(sa.Column(
                'revision', sa.Integer(), nullable=False, server_default='1'
            ))
        if 'last_edited_by_user_id' not in columns:
            batch.add_column(sa.Column(
                'last_edited_by_user_id', sa.String(length=36), nullable=True
            ))
        if 'hidden_for_user_ids' not in columns:
            batch.add_column(sa.Column('hidden_for_user_ids', sa.JSON(), nullable=True))

    columns = _existing_columns(bind, 'user_sessions')
    indexes = _existing_indexes(bind, 'user_sessions')

    if 'ix_user_sessions_last_edited_by_user_id' not in indexes:
        op.create_index(
            'ix_user_sessions_last_edited_by_user_id',
            'user_sessions',
            ['last_edited_by_user_id'],
        )
    if 'ix_user_sessions_org_session' not in indexes:
        op.create_index(
            'ix_user_sessions_org_session',
            'user_sessions',
            ['organization_id', 'session_id'],
        )

    # Backfill organization ownership for rows that never received one, because
    # `organization_id` used to come from the client and a save that omitted it
    # silently detached the project. Attribution order: created_by first, then
    # the home user. Personal-scope sentinels are excluded on purpose -- see the
    # module docstring.
    personal = ', '.join(f"'{sid}'" for sid in PERSONAL_SESSION_IDS)
    for attribution_column in ('created_by_user_id', 'user_id'):
        bind.execute(sa.text(f"""
            UPDATE user_sessions
            SET organization_id = (
                SELECT u.active_organization_id
                FROM users u
                WHERE u.id = user_sessions.{attribution_column}
            )
            WHERE organization_id IS NULL
              AND session_id NOT IN ({personal})
              AND {attribution_column} IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM users u
                  WHERE u.id = user_sessions.{attribution_column}
                    AND u.active_organization_id IS NOT NULL
              )
        """))

    # A sentinel must never carry an organization: it is personal state that
    # merely lives in this table. Clear any that picked one up.
    bind.execute(sa.text(f"""
        UPDATE user_sessions
        SET organization_id = NULL
        WHERE session_id IN ({personal})
          AND organization_id IS NOT NULL
    """))

    orphans = bind.execute(sa.text(f"""
        SELECT COUNT(*) FROM user_sessions
        WHERE organization_id IS NULL
          AND session_id NOT IN ({personal})
    """)).scalar()
    if orphans:
        # Quarantine, not a guess. These rows keep working as personal work;
        # they are simply not organization-owned until someone resolves them.
        logger.warning(
            '[org-ownership] %d session row(s) still have no organization after '
            'backfill (their attributed user has no active organization). They '
            'remain personal-scope and are NOT assigned to an organization.',
            orphans,
        )

    _report_forked_sessions(bind)


def downgrade():
    bind = op.get_bind()
    indexes = _existing_indexes(bind, 'user_sessions')

    if 'ix_user_sessions_org_session' in indexes:
        op.drop_index('ix_user_sessions_org_session', table_name='user_sessions')
    if 'ix_user_sessions_last_edited_by_user_id' in indexes:
        op.drop_index(
            'ix_user_sessions_last_edited_by_user_id', table_name='user_sessions'
        )

    columns = _existing_columns(bind, 'user_sessions')
    with op.batch_alter_table('user_sessions') as batch:
        if 'hidden_for_user_ids' in columns:
            batch.drop_column('hidden_for_user_ids')
        if 'last_edited_by_user_id' in columns:
            batch.drop_column('last_edited_by_user_id')
        if 'revision' in columns:
            batch.drop_column('revision')

    # The organization_id backfill is intentionally NOT reversed: the values it
    # wrote are correct ownership facts, and undoing them would re-detach
    # projects from their organization.
