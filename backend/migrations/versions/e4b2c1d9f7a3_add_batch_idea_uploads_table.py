"""add batch idea uploads table

Revision ID: e4b2c1d9f7a3
Revises: c9a7d4b2e1f0
Create Date: 2026-03-16 22:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e4b2c1d9f7a3"
down_revision = "c9a7d4b2e1f0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "batch_idea_uploads",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("ideas_json", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="uploaded"),
        sa.Column("ranking_result_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_batch_idea_uploads_user_id"), "batch_idea_uploads", ["user_id"], unique=False)
    op.create_index(op.f("ix_batch_idea_uploads_organization_id"), "batch_idea_uploads", ["organization_id"], unique=False)
    op.create_index(op.f("ix_batch_idea_uploads_status"), "batch_idea_uploads", ["status"], unique=False)
    op.create_index(op.f("ix_batch_idea_uploads_created_at"), "batch_idea_uploads", ["created_at"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_batch_idea_uploads_created_at"), table_name="batch_idea_uploads")
    op.drop_index(op.f("ix_batch_idea_uploads_status"), table_name="batch_idea_uploads")
    op.drop_index(op.f("ix_batch_idea_uploads_organization_id"), table_name="batch_idea_uploads")
    op.drop_index(op.f("ix_batch_idea_uploads_user_id"), table_name="batch_idea_uploads")
    op.drop_table("batch_idea_uploads")
