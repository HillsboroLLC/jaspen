"""add decision asset email deliveries

Revision ID: 8c4e2a1d7f90
Revises: 7b2d4e6f8a10
Create Date: 2026-08-01 17:38:00
"""

from alembic import op
import sqlalchemy as sa


revision = "8c4e2a1d7f90"
down_revision = "7b2d4e6f8a10"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "decision_asset_emails",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("thread_id", sa.String(length=255), nullable=False),
        sa.Column("evaluation_id", sa.String(length=36), nullable=True),
        sa.Column("scorecard_id", sa.String(length=255), nullable=True),
        sa.Column("recipient_email", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("output_types", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error_category", sa.String(length=80), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("provider_response", sa.String(length=80), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_decision_asset_email_user_key"),
    )
    op.create_index("ix_decision_asset_emails_user_id", "decision_asset_emails", ["user_id"], unique=False)
    op.create_index("ix_decision_asset_emails_organization_id", "decision_asset_emails", ["organization_id"], unique=False)
    op.create_index("ix_decision_asset_emails_thread_id", "decision_asset_emails", ["thread_id"], unique=False)
    op.create_index("ix_decision_asset_emails_evaluation_id", "decision_asset_emails", ["evaluation_id"], unique=False)
    op.create_index("ix_decision_asset_emails_scorecard_id", "decision_asset_emails", ["scorecard_id"], unique=False)
    op.create_index("ix_decision_asset_emails_status", "decision_asset_emails", ["status"], unique=False)
    op.create_index("ix_decision_asset_emails_created_at", "decision_asset_emails", ["created_at"], unique=False)
    op.create_index("ix_decision_asset_email_user_created", "decision_asset_emails", ["user_id", "created_at"], unique=False)


def downgrade():
    op.drop_index("ix_decision_asset_email_user_created", table_name="decision_asset_emails")
    op.drop_index("ix_decision_asset_emails_created_at", table_name="decision_asset_emails")
    op.drop_index("ix_decision_asset_emails_status", table_name="decision_asset_emails")
    op.drop_index("ix_decision_asset_emails_scorecard_id", table_name="decision_asset_emails")
    op.drop_index("ix_decision_asset_emails_evaluation_id", table_name="decision_asset_emails")
    op.drop_index("ix_decision_asset_emails_thread_id", table_name="decision_asset_emails")
    op.drop_index("ix_decision_asset_emails_organization_id", table_name="decision_asset_emails")
    op.drop_index("ix_decision_asset_emails_user_id", table_name="decision_asset_emails")
    op.drop_table("decision_asset_emails")
