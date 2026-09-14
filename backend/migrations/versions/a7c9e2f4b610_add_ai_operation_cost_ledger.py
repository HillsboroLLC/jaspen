"""add AI operation and provider attempt cost ledger

Revision ID: a7c9e2f4b610
Revises: f4c8d2a71e90
Create Date: 2026-09-13
"""

from alembic import op
import sqlalchemy as sa


revision = 'a7c9e2f4b610'
down_revision = 'f4c8d2a71e90'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'ai_operations',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=True),
        sa.Column('organization_id', sa.String(length=36), nullable=True),
        sa.Column('thread_id', sa.String(length=255), nullable=True),
        sa.Column('operation_type', sa.String(length=80), nullable=False),
        sa.Column('idempotency_key', sa.String(length=255), nullable=True),
        sa.Column('request_fingerprint', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=24), nullable=False),
        sa.Column('customer_visible', sa.Boolean(), nullable=False),
        sa.Column('subsidized', sa.Boolean(), nullable=False),
        sa.Column('subsidy_classification', sa.String(length=40), nullable=True),
        sa.Column('router_mode', sa.String(length=16), nullable=False),
        sa.Column('router_version', sa.String(length=64), nullable=False),
        sa.Column('route_class', sa.String(length=48), nullable=True),
        sa.Column('routing_reasons', sa.JSON(), nullable=True),
        sa.Column('legacy_provider', sa.String(length=32), nullable=True),
        sa.Column('legacy_model', sa.String(length=255), nullable=True),
        sa.Column('selected_provider', sa.String(length=32), nullable=True),
        sa.Column('selected_model', sa.String(length=255), nullable=True),
        sa.Column('final_provider', sa.String(length=32), nullable=True),
        sa.Column('final_model', sa.String(length=255), nullable=True),
        sa.Column('escalated', sa.Boolean(), nullable=False),
        sa.Column('policy_mode', sa.String(length=16), nullable=False),
        sa.Column('policy_version', sa.String(length=64), nullable=False),
        sa.Column('successful_provider_cost_usd', sa.Numeric(14, 8), nullable=True),
        sa.Column('total_provider_cost_usd', sa.Numeric(14, 8), nullable=True),
        sa.Column('projected_credits', sa.BigInteger(), nullable=False),
        sa.Column('charged_credits', sa.BigInteger(), nullable=False),
        sa.Column('settled_at', sa.DateTime(), nullable=True),
        sa.Column('error_code', sa.String(length=120), nullable=True),
        sa.Column('result_json', sa.JSON(), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key', name='uq_ai_operations_idempotency_key'),
    )
    op.create_index('ix_ai_operations_user_id', 'ai_operations', ['user_id'], unique=False)
    op.create_index('ix_ai_operations_organization_id', 'ai_operations', ['organization_id'], unique=False)
    op.create_index('ix_ai_operations_thread_id', 'ai_operations', ['thread_id'], unique=False)
    op.create_index('ix_ai_operations_operation_type', 'ai_operations', ['operation_type'], unique=False)
    op.create_index('ix_ai_operations_status', 'ai_operations', ['status'], unique=False)
    op.create_index('ix_ai_operations_subsidized', 'ai_operations', ['subsidized'], unique=False)
    op.create_index('ix_ai_operations_subsidy_classification', 'ai_operations', ['subsidy_classification'], unique=False)
    op.create_index('ix_ai_operations_route_class', 'ai_operations', ['route_class'], unique=False)
    op.create_index('ix_ai_operations_created_at', 'ai_operations', ['created_at'], unique=False)
    op.create_index('ix_ai_operations_user_created', 'ai_operations', ['user_id', 'created_at'], unique=False)

    op.create_table(
        'ai_provider_attempts',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('operation_id', sa.String(length=36), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('provider', sa.String(length=32), nullable=False),
        sa.Column('model', sa.String(length=255), nullable=True),
        sa.Column('outcome', sa.String(length=40), nullable=False),
        sa.Column('status_code', sa.Integer(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('input_tokens', sa.Integer(), nullable=False),
        sa.Column('output_tokens', sa.Integer(), nullable=False),
        sa.Column('raw_provider_cost_usd', sa.Numeric(14, 8), nullable=True),
        sa.Column('customer_billable', sa.Boolean(), nullable=False),
        sa.Column('error_code', sa.String(length=120), nullable=True),
        sa.Column('metadata_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['operation_id'], ['ai_operations.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('operation_id', 'sequence', name='uq_ai_provider_attempt_operation_sequence'),
    )
    op.create_index('ix_ai_provider_attempts_operation_id', 'ai_provider_attempts', ['operation_id'], unique=False)
    op.create_index('ix_ai_provider_attempts_created_at', 'ai_provider_attempts', ['created_at'], unique=False)


def downgrade():
    op.drop_index('ix_ai_provider_attempts_created_at', table_name='ai_provider_attempts')
    op.drop_index('ix_ai_provider_attempts_operation_id', table_name='ai_provider_attempts')
    op.drop_table('ai_provider_attempts')
    op.drop_index('ix_ai_operations_user_created', table_name='ai_operations')
    op.drop_index('ix_ai_operations_created_at', table_name='ai_operations')
    op.drop_index('ix_ai_operations_route_class', table_name='ai_operations')
    op.drop_index('ix_ai_operations_subsidized', table_name='ai_operations')
    op.drop_index('ix_ai_operations_subsidy_classification', table_name='ai_operations')
    op.drop_index('ix_ai_operations_status', table_name='ai_operations')
    op.drop_index('ix_ai_operations_operation_type', table_name='ai_operations')
    op.drop_index('ix_ai_operations_thread_id', table_name='ai_operations')
    op.drop_index('ix_ai_operations_organization_id', table_name='ai_operations')
    op.drop_index('ix_ai_operations_user_id', table_name='ai_operations')
    op.drop_table('ai_operations')
