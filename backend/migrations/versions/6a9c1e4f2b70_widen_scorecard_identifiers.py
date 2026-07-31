"""widen scorecard identifiers for legacy stable IDs

Revision ID: 6a9c1e4f2b70
Revises: 4f8a2d7c9b31
Create Date: 2026-07-31 13:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = '6a9c1e4f2b70'
down_revision = '4f8a2d7c9b31'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('scorecards') as batch:
        batch.alter_column(
            'id',
            existing_type=sa.String(length=36),
            type_=sa.String(length=255),
            existing_nullable=False,
        )
    with op.batch_alter_table('usage_events') as batch:
        batch.alter_column(
            'scorecard_id',
            existing_type=sa.String(length=36),
            type_=sa.String(length=255),
            existing_nullable=True,
        )


def downgrade():
    with op.batch_alter_table('usage_events') as batch:
        batch.alter_column(
            'scorecard_id',
            existing_type=sa.String(length=255),
            type_=sa.String(length=36),
            existing_nullable=True,
        )
    with op.batch_alter_table('scorecards') as batch:
        batch.alter_column(
            'id',
            existing_type=sa.String(length=255),
            type_=sa.String(length=36),
            existing_nullable=False,
        )
