"""add saved_utility_estimates table (Cost of Turnover utility)

Revision ID: a1b2c3d4e5f6
Revises: 3c4d5e6f7a8b
Create Date: 2026-07-16 09:00:00.000000

NOTE: This migration is provided with the Cost of Turnover utility but is NOT
applied automatically. The repository currently has multiple Alembic heads that
should be reconciled (alembic merge) before running `alembic upgrade head`. The
utility works fully without this table: anonymous users are never persisted, and
the authenticated "Save this estimate" flow degrades gracefully (frontend falls
back to a local save; the backend returns HTTP 503) until the table exists.
"""

from alembic import op
import sqlalchemy as sa


revision = "a1b2c3d4e5f6"
down_revision = "3c4d5e6f7a8b"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "saved_utility_estimates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("utility_type", sa.String(length=64), nullable=False, server_default="cost_of_turnover"),
        sa.Column("source", sa.String(length=80), nullable=True),
        sa.Column("calculator_version", sa.String(length=32), nullable=True),
        sa.Column("benchmark_version", sa.String(length=32), nullable=True),
        sa.Column("user_inputs", sa.JSON(), nullable=False),
        sa.Column("defaults_used", sa.JSON(), nullable=False),
        sa.Column("result_breakdown", sa.JSON(), nullable=False),
        sa.Column("built_using", sa.JSON(), nullable=False),
        sa.Column("total_low", sa.Integer(), nullable=True),
        sa.Column("total_mid", sa.Integer(), nullable=True),
        sa.Column("total_high", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_saved_utility_estimates_user_id", "saved_utility_estimates", ["user_id"]
    )
    op.create_index(
        "ix_saved_utility_estimates_user_utility",
        "saved_utility_estimates",
        ["user_id", "utility_type"],
    )


def downgrade():
    op.drop_index("ix_saved_utility_estimates_user_utility", table_name="saved_utility_estimates")
    op.drop_index("ix_saved_utility_estimates_user_id", table_name="saved_utility_estimates")
    op.drop_table("saved_utility_estimates")
