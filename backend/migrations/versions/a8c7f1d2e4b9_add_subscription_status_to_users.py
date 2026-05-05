"""add subscription_status to users

Revision ID: a8c7f1d2e4b9
Revises: c3b7d2f9a1e4
Create Date: 2026-05-05 10:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a8c7f1d2e4b9"
down_revision = "c3b7d2f9a1e4"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("subscription_status", sa.String(length=32), nullable=True))


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("subscription_status")
