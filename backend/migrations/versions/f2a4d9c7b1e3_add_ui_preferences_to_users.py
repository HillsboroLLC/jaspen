"""add ui_preferences to users

Revision ID: f2a4d9c7b1e3
Revises: b91d4e2a7c6f
Create Date: 2026-04-23 12:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "f2a4d9c7b1e3"
down_revision = "b91d4e2a7c6f"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("ui_preferences", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("ui_preferences")

