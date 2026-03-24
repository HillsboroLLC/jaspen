"""add user deactivation fields

Revision ID: 4a7b9c2d3e4f
Revises: 3e5f7a9c1b2d
Create Date: 2026-03-24 20:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "4a7b9c2d3e4f"
down_revision = "3e5f7a9c1b2d"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("deactivated_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("deactivated_by_user_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("deactivation_reason", sa.String(length=500), nullable=True))
        batch_op.add_column(sa.Column("recovery_expires_at", sa.DateTime(), nullable=True))
        batch_op.create_index(batch_op.f("ix_users_deactivated_by_user_id"), ["deactivated_by_user_id"], unique=False)
        batch_op.create_foreign_key(
            "fk_users_deactivated_by_user_id_users",
            "users",
            ["deactivated_by_user_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint("fk_users_deactivated_by_user_id_users", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_users_deactivated_by_user_id"))
        batch_op.drop_column("recovery_expires_at")
        batch_op.drop_column("deactivation_reason")
        batch_op.drop_column("deactivated_by_user_id")
        batch_op.drop_column("deactivated_at")
