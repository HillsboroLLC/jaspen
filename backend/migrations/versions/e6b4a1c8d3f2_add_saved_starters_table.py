"""add saved_starters table

Revision ID: e6b4a1c8d3f2
Revises: d24a9e8f1c32
Create Date: 2026-03-13 09:40:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e6b4a1c8d3f2"
down_revision = "d24a9e8f1c32"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "saved_starters",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("objective", sa.String(length=100), nullable=True),
        sa.Column("lever_defaults", sa.JSON(), nullable=True),
        sa.Column("scoring_weights", sa.JSON(), nullable=True),
        sa.Column("intake_context", sa.JSON(), nullable=True),
        sa.Column("is_shared", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_thread_id", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_saved_starters_created_at"), "saved_starters", ["created_at"], unique=False)
    op.create_index(op.f("ix_saved_starters_is_shared"), "saved_starters", ["is_shared"], unique=False)
    op.create_index(op.f("ix_saved_starters_organization_id"), "saved_starters", ["organization_id"], unique=False)
    op.create_index(op.f("ix_saved_starters_source_thread_id"), "saved_starters", ["source_thread_id"], unique=False)
    op.create_index(op.f("ix_saved_starters_user_id"), "saved_starters", ["user_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_saved_starters_user_id"), table_name="saved_starters")
    op.drop_index(op.f("ix_saved_starters_source_thread_id"), table_name="saved_starters")
    op.drop_index(op.f("ix_saved_starters_organization_id"), table_name="saved_starters")
    op.drop_index(op.f("ix_saved_starters_is_shared"), table_name="saved_starters")
    op.drop_index(op.f("ix_saved_starters_created_at"), table_name="saved_starters")
    op.drop_table("saved_starters")
