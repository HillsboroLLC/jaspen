"""add email verification and signup referral fields

Revision ID: 1c3d5f7a9b2c
Revises: 7d91e4c2ab5f
Create Date: 2026-03-24 10:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "1c3d5f7a9b2c"
down_revision = "7d91e4c2ab5f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("email_verified", sa.Boolean(), nullable=False, server_default=sa.true()))
    op.add_column("users", sa.Column("email_verified_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("email_verification_sent_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("referred_by_user_id", sa.String(length=36), nullable=True))
    op.add_column("users", sa.Column("signup_referral_code_used", sa.String(length=36), nullable=True))
    op.execute("UPDATE users SET email_verified = TRUE, email_verified_at = COALESCE(created_at, CURRENT_TIMESTAMP)")
    op.create_index(op.f("ix_users_referred_by_user_id"), "users", ["referred_by_user_id"], unique=False)
    op.create_foreign_key(
        "fk_users_referred_by_user_id_users",
        "users",
        "users",
        ["referred_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.alter_column("users", "email_verified", server_default=None)


def downgrade():
    op.drop_constraint("fk_users_referred_by_user_id_users", "users", type_="foreignkey")
    op.drop_index(op.f("ix_users_referred_by_user_id"), table_name="users")
    op.drop_column("users", "signup_referral_code_used")
    op.drop_column("users", "referred_by_user_id")
    op.drop_column("users", "email_verification_sent_at")
    op.drop_column("users", "email_verified_at")
    op.drop_column("users", "email_verified")
