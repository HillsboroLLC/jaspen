"""add access controls settings and approval status

Revision ID: 3e5f7a9c1b2d
Revises: 2d4f6a8b1c3e
Create Date: 2026-03-24 12:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "3e5f7a9c1b2d"
down_revision = "2d4f6a8b1c3e"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.PrimaryKeyConstraint("key"),
    )
    op.add_column("users", sa.Column("access_approval_status", sa.String(length=32), nullable=False, server_default="approved"))
    op.add_column("users", sa.Column("access_approved_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("access_reviewed_by_user_id", sa.String(length=36), nullable=True))
    op.execute("UPDATE users SET access_approval_status = 'approved', access_approved_at = COALESCE(created_at, CURRENT_TIMESTAMP)")
    op.create_index(op.f("ix_users_access_reviewed_by_user_id"), "users", ["access_reviewed_by_user_id"], unique=False)
    op.create_foreign_key(
        "fk_users_access_reviewed_by_user_id_users",
        "users",
        "users",
        ["access_reviewed_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column("users", "access_approval_status", server_default=None)


def downgrade():
    op.drop_constraint("fk_users_access_reviewed_by_user_id_users", "users", type_="foreignkey")
    op.drop_index(op.f("ix_users_access_reviewed_by_user_id"), table_name="users")
    op.drop_column("users", "access_reviewed_by_user_id")
    op.drop_column("users", "access_approved_at")
    op.drop_column("users", "access_approval_status")
    op.drop_table("app_settings")
