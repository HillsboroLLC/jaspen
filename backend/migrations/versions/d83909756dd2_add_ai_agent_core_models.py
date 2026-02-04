"""add ai agent core models (agent_threads, analyses, scoring_frameworks)

Revision ID: d83909756dd2
Revises: fe2e1a00739f
Create Date: 2026-02-02 16:00:00.000000

"""
from alembic import op
from sqlalchemy.dialects import postgresql
import sqlalchemy as sa
from datetime import datetime

# revision identifiers, used by Alembic.
revision = 'd83909756dd2'
down_revision = 'fe2e1a00739f'
branch_labels = None
depends_on = None


def upgrade():
    # === 1. Create scoring_frameworks table (no dependencies) ===
    op.create_table('scoring_frameworks',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('criteria', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('scoring_range', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('scale_labels', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('is_public', sa.Boolean(), nullable=False),
        sa.Column('is_system', sa.Boolean(), nullable=False),
        sa.Column('usage_count', sa.Integer(), nullable=False),
        sa.Column('version', sa.Integer(), nullable=False),
        sa.Column('parent_id', sa.String(length=36), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['parent_id'], ['scoring_frameworks.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_scoring_frameworks_created_at'), 'scoring_frameworks', ['created_at'], unique=False)
    op.create_index(op.f('ix_scoring_frameworks_deleted_at'), 'scoring_frameworks', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_scoring_frameworks_is_public'), 'scoring_frameworks', ['is_public'], unique=False)
    op.create_index(op.f('ix_scoring_frameworks_is_system'), 'scoring_frameworks', ['is_system'], unique=False)
    op.create_index(op.f('ix_scoring_frameworks_parent_id'), 'scoring_frameworks', ['parent_id'], unique=False)
    op.create_index(op.f('ix_scoring_frameworks_updated_at'), 'scoring_frameworks', ['updated_at'], unique=False)
    op.create_index(op.f('ix_scoring_frameworks_user_id'), 'scoring_frameworks', ['user_id'], unique=False)

    # === 2. Create agent_threads table (depends on projects) ===
    op.create_table('agent_threads',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('project_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('conversation_history', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('last_activity_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['project_id'], ['projects.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_agent_threads_created_at'), 'agent_threads', ['created_at'], unique=False)
    op.create_index(op.f('ix_agent_threads_deleted_at'), 'agent_threads', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_agent_threads_last_activity_at'), 'agent_threads', ['last_activity_at'], unique=False)
    op.create_index(op.f('ix_agent_threads_project_id'), 'agent_threads', ['project_id'], unique=False)
    op.create_index(op.f('ix_agent_threads_status'), 'agent_threads', ['status'], unique=False)
    op.create_index(op.f('ix_agent_threads_updated_at'), 'agent_threads', ['updated_at'], unique=False)
    op.create_index(op.f('ix_agent_threads_user_id'), 'agent_threads', ['user_id'], unique=False)

    # === 3. Create analyses table (depends on agent_threads and scoring_frameworks) ===
    op.create_table('analyses',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('thread_id', sa.String(length=36), nullable=False),
        sa.Column('scoring_framework_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('scores', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('overall_score', sa.Float(), nullable=False),
        sa.Column('status', sa.String(length=16), nullable=False),
        sa.Column('rank', sa.Integer(), nullable=True),
        sa.Column('strengths', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('weaknesses', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('opportunities', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('threats', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('recommendations', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('input_context', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('meta', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column('analyzed_at', sa.DateTime(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['thread_id'], ['agent_threads.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['scoring_framework_id'], ['scoring_frameworks.id'], ondelete='RESTRICT'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_analyses_analyzed_at'), 'analyses', ['analyzed_at'], unique=False)
    op.create_index(op.f('ix_analyses_created_at'), 'analyses', ['created_at'], unique=False)
    op.create_index(op.f('ix_analyses_deleted_at'), 'analyses', ['deleted_at'], unique=False)
    op.create_index(op.f('ix_analyses_overall_score'), 'analyses', ['overall_score'], unique=False)
    op.create_index(op.f('ix_analyses_rank'), 'analyses', ['rank'], unique=False)
    op.create_index(op.f('ix_analyses_scoring_framework_id'), 'analyses', ['scoring_framework_id'], unique=False)
    op.create_index(op.f('ix_analyses_status'), 'analyses', ['status'], unique=False)
    op.create_index(op.f('ix_analyses_thread_id'), 'analyses', ['thread_id'], unique=False)
    op.create_index(op.f('ix_analyses_updated_at'), 'analyses', ['updated_at'], unique=False)
    op.create_index(op.f('ix_analyses_user_id'), 'analyses', ['user_id'], unique=False)


def downgrade():
    # Drop in reverse order (respecting foreign key dependencies)

    # 3. Drop analyses table
    op.drop_index(op.f('ix_analyses_user_id'), table_name='analyses')
    op.drop_index(op.f('ix_analyses_updated_at'), table_name='analyses')
    op.drop_index(op.f('ix_analyses_thread_id'), table_name='analyses')
    op.drop_index(op.f('ix_analyses_status'), table_name='analyses')
    op.drop_index(op.f('ix_analyses_scoring_framework_id'), table_name='analyses')
    op.drop_index(op.f('ix_analyses_rank'), table_name='analyses')
    op.drop_index(op.f('ix_analyses_overall_score'), table_name='analyses')
    op.drop_index(op.f('ix_analyses_deleted_at'), table_name='analyses')
    op.drop_index(op.f('ix_analyses_created_at'), table_name='analyses')
    op.drop_index(op.f('ix_analyses_analyzed_at'), table_name='analyses')
    op.drop_table('analyses')

    # 2. Drop agent_threads table
    op.drop_index(op.f('ix_agent_threads_user_id'), table_name='agent_threads')
    op.drop_index(op.f('ix_agent_threads_updated_at'), table_name='agent_threads')
    op.drop_index(op.f('ix_agent_threads_status'), table_name='agent_threads')
    op.drop_index(op.f('ix_agent_threads_project_id'), table_name='agent_threads')
    op.drop_index(op.f('ix_agent_threads_last_activity_at'), table_name='agent_threads')
    op.drop_index(op.f('ix_agent_threads_deleted_at'), table_name='agent_threads')
    op.drop_index(op.f('ix_agent_threads_created_at'), table_name='agent_threads')
    op.drop_table('agent_threads')

    # 1. Drop scoring_frameworks table
    op.drop_index(op.f('ix_scoring_frameworks_user_id'), table_name='scoring_frameworks')
    op.drop_index(op.f('ix_scoring_frameworks_updated_at'), table_name='scoring_frameworks')
    op.drop_index(op.f('ix_scoring_frameworks_parent_id'), table_name='scoring_frameworks')
    op.drop_index(op.f('ix_scoring_frameworks_is_system'), table_name='scoring_frameworks')
    op.drop_index(op.f('ix_scoring_frameworks_is_public'), table_name='scoring_frameworks')
    op.drop_index(op.f('ix_scoring_frameworks_deleted_at'), table_name='scoring_frameworks')
    op.drop_index(op.f('ix_scoring_frameworks_created_at'), table_name='scoring_frameworks')
    op.drop_table('scoring_frameworks')
