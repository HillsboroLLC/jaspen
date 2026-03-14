"""add admin audit events table

Revision ID: 8f1e4a7c2d9b
Revises: 5c1b0f8e9a2d
Create Date: 2026-03-14 12:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8f1e4a7c2d9b"
down_revision = "5c1b0f8e9a2d"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "admin_audit_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("actor_user_id", sa.String(length=36), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("action", sa.String(length=100), nullable=False),
        sa.Column("target_user_id", sa.String(length=36), nullable=True),
        sa.Column("target_email", sa.String(length=255), nullable=True),
        sa.Column("details", sa.JSON(), nullable=True),
        sa.Column("remote_addr", sa.String(length=45), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.ForeignKeyConstraint(["actor_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_admin_audit_events_timestamp"), "admin_audit_events", ["timestamp"], unique=False)
    op.create_index(op.f("ix_admin_audit_events_actor_user_id"), "admin_audit_events", ["actor_user_id"], unique=False)
    op.create_index(op.f("ix_admin_audit_events_action"), "admin_audit_events", ["action"], unique=False)
    op.create_index(op.f("ix_admin_audit_events_target_user_id"), "admin_audit_events", ["target_user_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_admin_audit_events_target_user_id"), table_name="admin_audit_events")
    op.drop_index(op.f("ix_admin_audit_events_action"), table_name="admin_audit_events")
    op.drop_index(op.f("ix_admin_audit_events_actor_user_id"), table_name="admin_audit_events")
    op.drop_index(op.f("ix_admin_audit_events_timestamp"), table_name="admin_audit_events")
    op.drop_table("admin_audit_events")
