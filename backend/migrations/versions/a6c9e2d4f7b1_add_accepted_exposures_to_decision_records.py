"""add accepted exposures to decision records

Revision ID: a6c9e2d4f7b1
Revises: e5c3f18d92ab
Create Date: 2026-09-08 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a6c9e2d4f7b1"
down_revision = "e5c3f18d92ab"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "decision_records",
        sa.Column("accepted_exposures", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )


def downgrade():
    op.drop_column("decision_records", "accepted_exposures")
