"""Add customer-approved decision shares.

Revision ID: f1a2b3c4d5e6
Revises: e8f1a2b3c4d6
"""

from alembic import op
import sqlalchemy as sa


revision = "f1a2b3c4d5e6"
down_revision = "e8f1a2b3c4d6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "decision_shares",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("thread_id", sa.String(255), nullable=False),
        sa.Column("scorecard_id", sa.String(255), nullable=True),
        sa.Column("title", sa.String(255), nullable=True),
        sa.Column("snapshot_json", sa.JSON(), nullable=True),
        sa.Column("snapshot_sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("withdrawn_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_decision_shares_organization_id", "decision_shares", ["organization_id"])
    op.create_index("ix_decision_shares_user_id", "decision_shares", ["user_id"])
    op.create_index("ix_decision_shares_thread_id", "decision_shares", ["thread_id"])
    op.create_index("ix_decision_shares_created_at", "decision_shares", ["created_at"])
    op.create_index("ix_decision_shares_withdrawn_at", "decision_shares", ["withdrawn_at"])
    op.create_index("ix_decision_shares_org_created", "decision_shares", ["organization_id", "created_at"])
    op.create_index("ix_decision_shares_user_created", "decision_shares", ["user_id", "created_at"])


def downgrade():
    op.drop_table("decision_shares")
