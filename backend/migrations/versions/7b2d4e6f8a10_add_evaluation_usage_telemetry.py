"""add evaluation-level usage telemetry

Revision ID: 7b2d4e6f8a10
Revises: 6a9c1e4f2b70
Create Date: 2026-07-31 16:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = '7b2d4e6f8a10'
down_revision = '6a9c1e4f2b70'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('scorecards') as batch:
        batch.add_column(sa.Column('evaluation_id', sa.String(length=36), nullable=True))
        batch.create_index('ix_scorecards_evaluation_id', ['evaluation_id'], unique=False)

    with op.batch_alter_table('usage_events') as batch:
        batch.add_column(sa.Column('evaluation_id', sa.String(length=36), nullable=True))
        batch.add_column(sa.Column('plan_key', sa.String(length=32), nullable=True))
        batch.add_column(sa.Column('attachment_count', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('extracted_attachment_tokens', sa.Integer(), nullable=False, server_default='0'))
        batch.create_index('ix_usage_events_evaluation_id', ['evaluation_id'], unique=False)
        batch.create_index('ix_usage_events_plan_key', ['plan_key'], unique=False)


def downgrade():
    with op.batch_alter_table('usage_events') as batch:
        batch.drop_index('ix_usage_events_plan_key')
        batch.drop_index('ix_usage_events_evaluation_id')
        batch.drop_column('extracted_attachment_tokens')
        batch.drop_column('attachment_count')
        batch.drop_column('plan_key')
        batch.drop_column('evaluation_id')

    with op.batch_alter_table('scorecards') as batch:
        batch.drop_index('ix_scorecards_evaluation_id')
        batch.drop_column('evaluation_id')
