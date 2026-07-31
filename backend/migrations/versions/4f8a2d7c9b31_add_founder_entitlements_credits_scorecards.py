"""add Founder entitlements, persistent credits, peer scorecards, usage telemetry

Revision ID: 4f8a2d7c9b31
Revises: f8d5c3b0e2a7
Create Date: 2026-07-31 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = '4f8a2d7c9b31'
down_revision = 'f8d5c3b0e2a7'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        'account_entitlements',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=True),
        sa.Column('entitlement_key', sa.String(length=80), nullable=False),
        sa.Column('source', sa.String(length=80), nullable=False),
        sa.Column('external_reference', sa.String(length=255), nullable=True),
        sa.Column('grant_metadata', sa.JSON(), nullable=True),
        sa.Column('granted_at', sa.DateTime(), nullable=False),
        sa.Column('revoked_at', sa.DateTime(), nullable=True),
        sa.Column('revoke_reason', sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('external_reference'),
        sa.UniqueConstraint('user_id', 'entitlement_key', name='uq_account_entitlements_user_key'),
    )
    for column in ('user_id', 'organization_id', 'entitlement_key', 'external_reference', 'granted_at', 'revoked_at'):
        op.create_index(f'ix_account_entitlements_{column}', 'account_entitlements', [column], unique=column == 'external_reference')

    op.create_table(
        'persistent_credit_grants',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=True),
        sa.Column('entitlement_id', sa.String(length=36), nullable=True),
        sa.Column('source', sa.String(length=80), nullable=False),
        sa.Column('original_amount', sa.BigInteger(), nullable=False),
        sa.Column('remaining_amount', sa.BigInteger(), nullable=False),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('external_reference', sa.String(length=255), nullable=False),
        sa.Column('stripe_checkout_id', sa.String(length=255), nullable=True),
        sa.Column('stripe_invoice_id', sa.String(length=255), nullable=True),
        sa.Column('grant_metadata', sa.JSON(), nullable=True),
        sa.Column('granted_at', sa.DateTime(), nullable=False),
        sa.Column('reversed_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['entitlement_id'], ['account_entitlements.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('external_reference'),
    )
    for column in ('user_id', 'organization_id', 'entitlement_id', 'source', 'status', 'external_reference', 'stripe_checkout_id', 'stripe_invoice_id', 'granted_at'):
        op.create_index(f'ix_persistent_credit_grants_{column}', 'persistent_credit_grants', [column], unique=column == 'external_reference')

    op.create_table(
        'scorecards',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('organization_id', sa.String(length=36), nullable=True),
        sa.Column('thread_id', sa.String(length=255), nullable=False),
        sa.Column('session_id', sa.String(length=255), nullable=True),
        sa.Column('decision_record_id', sa.String(length=36), nullable=True),
        sa.Column('project_name', sa.String(length=255), nullable=False),
        sa.Column('rubric', sa.JSON(), nullable=True),
        sa.Column('evidence', sa.JSON(), nullable=True),
        sa.Column('score', sa.Numeric(precision=8, scale=3), nullable=True),
        sa.Column('assumptions', sa.JSON(), nullable=True),
        sa.Column('recommendation', sa.JSON(), nullable=True),
        sa.Column('execution_plan_ref', sa.String(length=255), nullable=True),
        sa.Column('data', sa.JSON(), nullable=False),
        sa.Column('search_metadata', sa.JSON(), nullable=True),
        sa.Column('source', sa.String(length=40), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.Column('archived_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['decision_record_id'], ['decision_records.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    for column in ('user_id', 'organization_id', 'thread_id', 'session_id', 'decision_record_id', 'project_name', 'score', 'execution_plan_ref', 'source', 'created_at', 'archived_at'):
        op.create_index(f'ix_scorecards_{column}', 'scorecards', [column], unique=False)
    op.create_index('ix_scorecards_user_thread_created', 'scorecards', ['user_id', 'thread_id', 'created_at'], unique=False)

    with op.batch_alter_table('usage_events') as batch:
        batch.add_column(sa.Column('organization_id', sa.String(length=36), nullable=True))
        batch.add_column(sa.Column('endpoint', sa.String(length=120), nullable=True))
        batch.add_column(sa.Column('operation_type', sa.String(length=80), nullable=True))
        batch.add_column(sa.Column('raw_provider_cost_usd', sa.Numeric(precision=14, scale=8), nullable=True))
        batch.add_column(sa.Column('reserved_credits', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('settled_credits', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('success', sa.Boolean(), nullable=False, server_default=sa.text('true')))
        batch.add_column(sa.Column('error_code', sa.String(length=120), nullable=True))
        batch.add_column(sa.Column('scorecard_id', sa.String(length=36), nullable=True))
        batch.add_column(sa.Column('metadata_json', sa.JSON(), nullable=True))
        batch.create_foreign_key('fk_usage_events_organization_id', 'organizations', ['organization_id'], ['id'], ondelete='SET NULL')
    for column in ('organization_id', 'endpoint', 'operation_type', 'success', 'scorecard_id'):
        op.create_index(f'ix_usage_events_{column}', 'usage_events', [column], unique=False)

    op.create_table(
        'persistent_credit_transactions',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('grant_id', sa.String(length=36), nullable=False),
        sa.Column('user_id', sa.String(length=36), nullable=False),
        sa.Column('transaction_type', sa.String(length=32), nullable=False),
        sa.Column('amount', sa.BigInteger(), nullable=False),
        sa.Column('balance_after', sa.BigInteger(), nullable=False),
        sa.Column('idempotency_key', sa.String(length=255), nullable=True),
        sa.Column('usage_event_id', sa.Integer(), nullable=True),
        sa.Column('transaction_metadata', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['grant_id'], ['persistent_credit_grants.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['usage_event_id'], ['usage_events.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('idempotency_key'),
    )
    for column in ('grant_id', 'user_id', 'transaction_type', 'idempotency_key', 'usage_event_id', 'created_at'):
        op.create_index(f'ix_persistent_credit_transactions_{column}', 'persistent_credit_transactions', [column], unique=column == 'idempotency_key')


def downgrade():
    op.drop_table('persistent_credit_transactions')
    for column in ('organization_id', 'endpoint', 'operation_type', 'success', 'scorecard_id'):
        op.drop_index(f'ix_usage_events_{column}', table_name='usage_events')
    with op.batch_alter_table('usage_events') as batch:
        batch.drop_constraint('fk_usage_events_organization_id', type_='foreignkey')
        for column in ('metadata_json', 'scorecard_id', 'error_code', 'success', 'settled_credits', 'reserved_credits', 'raw_provider_cost_usd', 'operation_type', 'endpoint', 'organization_id'):
            batch.drop_column(column)
    op.drop_table('scorecards')
    op.drop_table('persistent_credit_grants')
    op.drop_table('account_entitlements')
