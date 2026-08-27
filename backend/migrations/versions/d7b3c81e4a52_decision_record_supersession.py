"""Supersession linkage for Decision Records (Phase 5).

Additive only. Adds ONE forward link and its timestamp:

  * supersedes_id  -- self-referential FK, indexed. The new record names the
                      decision it replaces.
  * superseded_at  -- when that link was made.

Deliberately NOT added:

  * `superseded_by_id`. It is the inverse of supersedes_id and can desync from
    it; a desynced pair makes a record claim a current-state it does not have,
    which is the worst failure mode for institutional memory. The reverse
    direction is a single indexed query instead.

  * `is_current`. A stored boolean must be rewritten on every supersession and
    silently lies the moment an update is missed. Current state is DERIVED --
    see current_state() in app/decision_records.py.

  * `effective_from` / `effective_until`. Nothing in the product captures when
    a decision takes EFFECT, so these would fabricate a signal. `decided_at`
    remains the only temporal marker of the decision itself.

NO BACKFILL. Every existing record gets supersedes_id = NULL, which
current_state() reports as UNKNOWN rather than CURRENT -- because none of them
carry a human decision, and calling them current would assert an
organizational position nobody ever took. Historical truth stays honest.

Revision ID: d7b3c81e4a52
Revises: c4a1f7e93b28
Create Date: 2026-08-27
"""
import logging

import sqlalchemy as sa
from alembic import op


revision = 'd7b3c81e4a52'
down_revision = 'c4a1f7e93b28'
branch_labels = None
depends_on = None

logger = logging.getLogger('alembic.runtime.migration')


def _existing_columns(bind, table):
    return {col['name'] for col in sa.inspect(bind).get_columns(table)}


def _existing_indexes(bind, table):
    return {idx['name'] for idx in sa.inspect(bind).get_indexes(table)}


def upgrade():
    bind = op.get_bind()
    columns = _existing_columns(bind, 'decision_records')

    with op.batch_alter_table('decision_records') as batch:
        if 'supersedes_id' not in columns:
            batch.add_column(sa.Column('supersedes_id', sa.String(length=36), nullable=True))
        if 'superseded_at' not in columns:
            batch.add_column(sa.Column('superseded_at', sa.DateTime(), nullable=True))

    if 'ix_decision_records_supersedes_id' not in _existing_indexes(bind, 'decision_records'):
        op.create_index(
            'ix_decision_records_supersedes_id',
            'decision_records',
            ['supersedes_id'],
        )

    unknown = bind.execute(sa.text(
        'SELECT COUNT(*) FROM decision_records WHERE final_decision IS NULL'
    )).scalar()
    if unknown:
        logger.info(
            '[supersession] %d existing record(s) have no human decision and no '
            'successor; they report current_state=UNKNOWN, not CURRENT. No '
            'supersession relationships were invented.',
            unknown,
        )


def downgrade():
    bind = op.get_bind()

    if 'ix_decision_records_supersedes_id' in _existing_indexes(bind, 'decision_records'):
        op.drop_index('ix_decision_records_supersedes_id', table_name='decision_records')

    columns = _existing_columns(bind, 'decision_records')
    with op.batch_alter_table('decision_records') as batch:
        if 'superseded_at' in columns:
            batch.drop_column('superseded_at')
        if 'supersedes_id' in columns:
            batch.drop_column('supersedes_id')
