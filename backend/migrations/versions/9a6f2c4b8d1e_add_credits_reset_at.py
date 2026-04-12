"""add credits_reset_at to users

Revision ID: 9a6f2c4b8d1e
Revises: e4b2c1d9f7a3
Create Date: 2026-04-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "9a6f2c4b8d1e"
down_revision = "e4b2c1d9f7a3"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("users", sa.Column("credits_reset_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("users", "credits_reset_at")
