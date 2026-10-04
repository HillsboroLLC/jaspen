"""add public share links for scorecards and trade-offs

Revision ID: b3e8f1c5a902
Revises: a7c9e2f4b610
Create Date: 2026-09-26
"""

from alembic import op
import sqlalchemy as sa


revision = 'b3e8f1c5a902'
down_revision = 'a7c9e2f4b610'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'users',
        sa.Column('sharing_disabled', sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    op.create_table(
        'shared_artifacts',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('token', sa.String(length=64), nullable=False),
        sa.Column('owner_user_id', sa.String(length=36), nullable=False),
        sa.Column('thread_id', sa.String(length=255), nullable=False),
        sa.Column('artifact_type', sa.String(length=24), nullable=False),
        sa.Column('source_id', sa.String(length=255), nullable=True),
        sa.Column('title', sa.String(length=255), nullable=False),
        sa.Column('snapshot_json', sa.JSON(), nullable=False),
        sa.Column('include_evidence', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('revoked_by', sa.String(length=16), nullable=True),
        sa.Column('revoked_reason', sa.String(length=255), nullable=True),
        sa.Column('view_count', sa.Integer(), nullable=False),
        sa.Column('last_viewed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['owner_user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_shared_artifacts_token', 'shared_artifacts', ['token'], unique=True)
    op.create_index('ix_shared_artifacts_owner_user_id', 'shared_artifacts', ['owner_user_id'])
    op.create_index('ix_shared_artifacts_thread_id', 'shared_artifacts', ['thread_id'])
    op.create_index('ix_shared_artifacts_created_at', 'shared_artifacts', ['created_at'])
    op.create_index('ix_shared_artifacts_owner_created', 'shared_artifacts', ['owner_user_id', 'created_at'])

    op.create_table(
        'shared_artifact_reports',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('shared_artifact_id', sa.String(length=36), nullable=False),
        sa.Column('reason', sa.String(length=40), nullable=False),
        sa.Column('details', sa.Text(), nullable=True),
        sa.Column('reporter_fingerprint', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['shared_artifact_id'], ['shared_artifacts.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_shared_artifact_reports_shared_artifact_id', 'shared_artifact_reports', ['shared_artifact_id'])
    op.create_index('ix_shared_artifact_reports_status', 'shared_artifact_reports', ['status'])
    op.create_index('ix_shared_artifact_reports_created_at', 'shared_artifact_reports', ['created_at'])


def downgrade():
    op.drop_index('ix_shared_artifact_reports_created_at', table_name='shared_artifact_reports')
    op.drop_index('ix_shared_artifact_reports_status', table_name='shared_artifact_reports')
    op.drop_index('ix_shared_artifact_reports_shared_artifact_id', table_name='shared_artifact_reports')
    op.drop_table('shared_artifact_reports')
    op.drop_index('ix_shared_artifacts_owner_created', table_name='shared_artifacts')
    op.drop_index('ix_shared_artifacts_created_at', table_name='shared_artifacts')
    op.drop_index('ix_shared_artifacts_thread_id', table_name='shared_artifacts')
    op.drop_index('ix_shared_artifacts_owner_user_id', table_name='shared_artifacts')
    op.drop_index('ix_shared_artifacts_token', table_name='shared_artifacts')
    op.drop_table('shared_artifacts')
    op.drop_column('users', 'sharing_disabled')
