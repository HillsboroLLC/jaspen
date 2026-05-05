"""add industry and company_size to users

Revision ID: b4f2e1a9c3d7
Revises: a8c7f1d2e4b9
Create Date: 2026-05-05 11:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b4f2e1a9c3d7"
down_revision = "a8c7f1d2e4b9"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("industry", sa.String(length=120), nullable=True))
        batch_op.add_column(sa.Column("company_size", sa.String(length=32), nullable=True))


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_column("company_size")
        batch_op.drop_column("industry")
