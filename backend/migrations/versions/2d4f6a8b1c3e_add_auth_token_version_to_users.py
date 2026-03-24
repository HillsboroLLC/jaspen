"""add auth token version to users

Revision ID: 2d4f6a8b1c3e
Revises: 1c3d5f7a9b2c
Create Date: 2026-03-24 11:15:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "2d4f6a8b1c3e"
down_revision = "1c3d5f7a9b2c"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("auth_token_version", sa.Integer(), nullable=False, server_default="0"))
    op.alter_column("users", "auth_token_version", server_default=None)


def downgrade():
    op.drop_column("users", "auth_token_version")
