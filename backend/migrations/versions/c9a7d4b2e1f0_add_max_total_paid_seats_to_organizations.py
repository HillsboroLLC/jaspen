"""add max total paid seats to organizations

Revision ID: c9a7d4b2e1f0
Revises: b7c2d4e6f8a1
Create Date: 2026-03-15 12:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c9a7d4b2e1f0"
down_revision = "b7c2d4e6f8a1"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("organizations", sa.Column("max_total_paid_seats", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("organizations", "max_total_paid_seats")
