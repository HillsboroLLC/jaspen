"""Enforce attribution and supersession foreign keys.

The Phase 1 and Phase 5 migrations added ``last_edited_by_user_id`` and
``supersedes_id`` as columns, but did not install the foreign keys declared by
the ORM models.  Without the database constraints, deleting a user or a prior
Decision Record can leave dangling identifiers even though the application ORM
metadata promises ``ON DELETE SET NULL`` behavior.

Revision ID: f4c8d2a71e90
Revises: e2f9a4d17c63
Create Date: 2026-09-12
"""

import sqlalchemy as sa
from alembic import op


revision = 'f4c8d2a71e90'
down_revision = 'e2f9a4d17c63'
branch_labels = None
depends_on = None


SESSION_EDITOR_FK = 'fk_user_sessions_last_edited_by_user_id_users'
SUPERSESSION_FK = 'fk_decision_records_supersedes_id_decision_records'
NAMING_CONVENTION = {
    'fk': 'fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s',
}


def _foreign_key(bind, table, constrained_column, referred_table):
    for foreign_key in sa.inspect(bind).get_foreign_keys(table):
        if (
            foreign_key.get('constrained_columns') == [constrained_column]
            and foreign_key.get('referred_table') == referred_table
        ):
            return foreign_key
    return None


def upgrade():
    bind = op.get_bind()

    if not _foreign_key(bind, 'user_sessions', 'last_edited_by_user_id', 'users'):
        with op.batch_alter_table(
            'user_sessions', naming_convention=NAMING_CONVENTION
        ) as batch:
            batch.create_foreign_key(
                SESSION_EDITOR_FK,
                'users',
                ['last_edited_by_user_id'],
                ['id'],
                ondelete='SET NULL',
            )

    if not _foreign_key(bind, 'decision_records', 'supersedes_id', 'decision_records'):
        with op.batch_alter_table(
            'decision_records', naming_convention=NAMING_CONVENTION
        ) as batch:
            batch.create_foreign_key(
                SUPERSESSION_FK,
                'decision_records',
                ['supersedes_id'],
                ['id'],
                ondelete='SET NULL',
            )


def downgrade():
    bind = op.get_bind()

    supersession = _foreign_key(
        bind, 'decision_records', 'supersedes_id', 'decision_records'
    )
    if supersession:
        with op.batch_alter_table(
            'decision_records', naming_convention=NAMING_CONVENTION
        ) as batch:
            batch.drop_constraint(
                supersession.get('name') or SUPERSESSION_FK,
                type_='foreignkey',
            )

    session_editor = _foreign_key(
        bind, 'user_sessions', 'last_edited_by_user_id', 'users'
    )
    if session_editor:
        with op.batch_alter_table(
            'user_sessions', naming_convention=NAMING_CONVENTION
        ) as batch:
            batch.drop_constraint(
                session_editor.get('name') or SESSION_EDITOR_FK,
                type_='foreignkey',
            )
