"""add scenarios_json to user_sessions

Revision ID: 3c5f9a2b7e10
Revises: f6e7d4c9b21a
Create Date: 2026-03-18 18:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "3c5f9a2b7e10"
down_revision = "f6e7d4c9b21a"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "user_sessions",
        sa.Column("scenarios_json", sa.JSON(), nullable=True),
    )


def downgrade():
    op.drop_column("user_sessions", "scenarios_json")
