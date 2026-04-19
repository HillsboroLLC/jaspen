"""add credits_reset_at to users

Revision ID: 9a6f2c4b8d1e
Revises: e4b2c1d9f7a3
Create Date: 2026-04-11 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect


# revision identifiers, used by Alembic.
revision = "9a6f2c4b8d1e"
down_revision = "e4b2c1d9f7a3"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col.get("name") for col in inspector.get_columns("users")}
    if "credits_reset_at" not in columns:
        op.add_column("users", sa.Column("credits_reset_at", sa.DateTime(), nullable=True))


def downgrade():
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = {col.get("name") for col in inspector.get_columns("users")}
    if "credits_reset_at" in columns:
        op.drop_column("users", "credits_reset_at")
