"""Decision Record attribution survives user departure (Phase 6).

`decision_records.user_id` was CASCADE and NOT NULL. Phase 2 catalogued it as a
latent risk and deferred it: no user-deletion path existed, and everything on
the record could be re-derived from the project it came from.

Phase 6 changes that calculus. Outcomes and lessons are HUMAN-AUTHORED
institutional learning -- what actually happened, and what the organization
concluded from it. They cannot be reconstructed from anything. Cascading them
away with the person who happened to type them would destroy precisely the
knowledge the Memory Warehouse exists to keep.

So: user_id becomes nullable with ON DELETE SET NULL. The record stays owned by
its organization, and attribution survives as name snapshots -- in the payload's
`attribution.created_by_name`, and on every outcome and lesson entry's
`recorded_by_name`.

This is the SMALLEST change that protects the new knowledge: one column, on the
one table that now holds it. The other seven CASCADE FKs catalogued in Phase 2
remain documented and unchanged -- they carry derived or personal artifacts, and
there is still no user-deletion path in the codebase.

SQLite cannot ALTER a column, so batch_alter_table rebuilds the table. No data
is transformed: every existing row keeps its user_id.

Revision ID: e2f9a4d17c63
Revises: d7b3c81e4a52
Create Date: 2026-08-27
"""
import sqlalchemy as sa
from alembic import op


revision = 'e2f9a4d17c63'
down_revision = 'd7b3c81e4a52'
branch_labels = None
depends_on = None


def _user_id_column(bind):
    for col in sa.inspect(bind).get_columns('decision_records'):
        if col['name'] == 'user_id':
            return col
    return None


def upgrade():
    bind = op.get_bind()
    column = _user_id_column(bind)
    if column is None or column.get('nullable') is True:
        return

    with op.batch_alter_table('decision_records') as batch:
        batch.alter_column(
            'user_id',
            existing_type=sa.String(length=36),
            nullable=True,
        )


class RetainedRecordsBlockDowngrade(Exception):
    """Raised when reversing would invalidate retained organizational records."""


def downgrade():
    """Guarded reversal.

    Restoring NOT NULL / CASCADE is safe ONLY while every Decision Record still
    has a live author. Once a contributor has been removed, their records carry
    user_id NULL by design -- that is the whole point of this migration -- and
    reversing it would either fail on the constraint or, worse, invite someone
    to "fix" the data by inventing an author or deleting the record.

    So the reversal checks first and refuses loudly rather than guessing. It
    never fabricates a user, never reassigns attribution, and never deletes a
    record.
    """
    bind = op.get_bind()

    orphaned = bind.execute(sa.text(
        'SELECT COUNT(*) FROM decision_records WHERE user_id IS NULL'
    )).scalar() or 0

    if orphaned:
        sample = [
            row[0] for row in bind.execute(sa.text(
                'SELECT id FROM decision_records WHERE user_id IS NULL LIMIT 5'
            )).fetchall()
        ]
        raise RetainedRecordsBlockDowngrade(
            f'Cannot downgrade {revision}: {orphaned} Decision Record(s) have no '
            f'attributed user because their author was removed, and restoring '
            f'NOT NULL would invalidate exactly the organizational records this '
            f'migration exists to retain. Their outcomes and lessons are '
            f'human-authored and cannot be re-derived. Resolve deliberately '
            f'before downgrading -- do not fabricate an author or delete the '
            f'records. Affected ids (first 5): {sample}'
        )

    column = _user_id_column(bind)
    if column is None or column.get('nullable') is False:
        return

    with op.batch_alter_table('decision_records') as batch:
        batch.alter_column(
            'user_id',
            existing_type=sa.String(length=36),
            nullable=False,
        )
