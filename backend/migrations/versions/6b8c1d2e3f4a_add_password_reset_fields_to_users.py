"""add password reset fields to users

Revision ID: 6b8c1d2e3f4a
Revises: 4a7b9c2d3e4f
Create Date: 2026-03-24 22:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "6b8c1d2e3f4a"
down_revision = "4a7b9c2d3e4f"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("password_reset_requested_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("password_reset_version", sa.Integer(), nullable=False, server_default="0"))

    op.execute("UPDATE users SET password_reset_version = 0 WHERE password_reset_version IS NULL")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column("password_reset_version", server_default=None)


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("password_reset_version")
        batch_op.drop_column("password_reset_requested_at")
