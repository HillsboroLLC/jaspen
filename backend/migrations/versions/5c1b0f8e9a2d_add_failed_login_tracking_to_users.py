"""add failed login tracking to users

Revision ID: 5c1b0f8e9a2d
Revises: 7a1b3c4d5e6f
Create Date: 2026-03-14 02:45:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "5c1b0f8e9a2d"
down_revision = "7a1b3c4d5e6f"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("failed_login_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("locked_until", sa.DateTime(), nullable=True))
    op.alter_column("users", "failed_login_attempts", server_default=None)


def downgrade():
    op.drop_column("users", "locked_until")
    op.drop_column("users", "failed_login_attempts")
