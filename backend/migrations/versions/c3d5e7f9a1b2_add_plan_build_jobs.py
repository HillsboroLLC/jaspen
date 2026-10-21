"""Add background execution-plan build jobs.

Revision ID: c3d5e7f9a1b2
Revises: b7e2c9a4f1d6
"""

from alembic import op
import sqlalchemy as sa


revision = "c3d5e7f9a1b2"
down_revision = "b7e2c9a4f1d6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "plan_build_jobs",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="running"),
        sa.Column("request_json", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=True),
        sa.Column("result_status", sa.Integer(), nullable=True),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_plan_build_jobs_user_id", "plan_build_jobs", ["user_id"])
    op.create_index("ix_plan_build_jobs_thread_id", "plan_build_jobs", ["thread_id"])


def downgrade():
    op.drop_index("ix_plan_build_jobs_thread_id", table_name="plan_build_jobs")
    op.drop_index("ix_plan_build_jobs_user_id", table_name="plan_build_jobs")
    op.drop_table("plan_build_jobs")
