"""add org_idea_ledger + soft-delete fields on user_sessions

Revision ID: d4e5f6a7b8c9
Revises: b4f2e1a9c3d7
Create Date: 2026-05-17 08:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d4e5f6a7b8c9"
down_revision = "b4f2e1a9c3d7"
branch_labels = None
depends_on = None


def upgrade():
    # --- user_sessions: soft-delete columns ---------------------------------
    with op.batch_alter_table("user_sessions") as batch:
        batch.add_column(sa.Column("archived_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("purge_after", sa.DateTime(), nullable=True))
    op.create_index(
        "ix_user_sessions_archived_at", "user_sessions", ["archived_at"], unique=False
    )
    op.create_index(
        "ix_user_sessions_purge_after", "user_sessions", ["purge_after"], unique=False
    )
    op.create_index(
        "ix_user_sessions_user_archived",
        "user_sessions",
        ["user_id", "archived_at"],
        unique=False,
    )

    # --- org_idea_ledger ----------------------------------------------------
    op.create_table(
        "org_idea_ledger",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("ledger_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("originating_user_id", sa.String(length=36), nullable=True),
        sa.Column("source_session_id", sa.String(length=255), nullable=True),
        sa.Column("idea_category", sa.String(length=100), nullable=True),
        sa.Column("industry", sa.String(length=100), nullable=True),
        sa.Column("company_size", sa.String(length=50), nullable=True),
        sa.Column("jaspen_score", sa.Integer(), nullable=True),
        sa.Column("score_category", sa.String(length=20), nullable=True),
        sa.Column("dimensions", sa.JSON(), nullable=True),
        sa.Column("risk_tags", sa.JSON(), nullable=True),
        sa.Column("recommendation_tags", sa.JSON(), nullable=True),
        sa.Column("had_tradeoff", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("had_execution_plan", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("phase_count", sa.Integer(), nullable=True),
        sa.Column("task_count", sa.Integer(), nullable=True),
        sa.Column("objective", sa.String(length=50), nullable=True),
        sa.Column("model_tier_used", sa.String(length=32), nullable=True),
        sa.Column("outcome", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("archived_at", sa.DateTime(), nullable=True),
        sa.Column("purged_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["originating_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ledger_id"),
    )
    op.create_index("ix_org_idea_ledger_ledger_id", "org_idea_ledger", ["ledger_id"], unique=True)
    op.create_index("ix_org_idea_ledger_organization_id", "org_idea_ledger", ["organization_id"], unique=False)
    op.create_index("ix_org_idea_ledger_originating_user_id", "org_idea_ledger", ["originating_user_id"], unique=False)
    op.create_index("ix_org_idea_ledger_source_session_id", "org_idea_ledger", ["source_session_id"], unique=False)
    op.create_index("ix_org_idea_ledger_idea_category", "org_idea_ledger", ["idea_category"], unique=False)
    op.create_index("ix_org_idea_ledger_industry", "org_idea_ledger", ["industry"], unique=False)
    op.create_index("ix_org_idea_ledger_jaspen_score", "org_idea_ledger", ["jaspen_score"], unique=False)
    op.create_index("ix_org_idea_ledger_score_category", "org_idea_ledger", ["score_category"], unique=False)
    op.create_index("ix_org_idea_ledger_outcome", "org_idea_ledger", ["outcome"], unique=False)
    op.create_index("ix_org_idea_ledger_created_at", "org_idea_ledger", ["created_at"], unique=False)
    op.create_index("ix_org_idea_ledger_archived_at", "org_idea_ledger", ["archived_at"], unique=False)
    op.create_index("ix_org_idea_ledger_purged_at", "org_idea_ledger", ["purged_at"], unique=False)
    op.create_index("ix_org_idea_ledger_org_score", "org_idea_ledger", ["organization_id", "jaspen_score"], unique=False)
    op.create_index("ix_org_idea_ledger_industry_score", "org_idea_ledger", ["industry", "jaspen_score"], unique=False)
    op.create_index("ix_org_idea_ledger_org_created", "org_idea_ledger", ["organization_id", "created_at"], unique=False)


def downgrade():
    # org_idea_ledger
    op.drop_index("ix_org_idea_ledger_org_created", table_name="org_idea_ledger")
    op.drop_index("ix_org_idea_ledger_industry_score", table_name="org_idea_ledger")
    op.drop_index("ix_org_idea_ledger_org_score", table_name="org_idea_ledger")
    op.drop_index("ix_org_idea_ledger_purged_at", table_name="org_idea_ledger")
    op.drop_index("ix_org_idea_ledger_archived_at", table_name="org_idea_ledger")
    op.drop_index("ix_org_idea_ledger_created_at", table_name="org_idea_ledger")
    op.drop_index("ix_org_idea_ledger_outcome", table_name="org_idea_ledger")
    op.drop_index("ix_org_idea_ledger_score_category", table_name="org_idea_ledger")
    op.drop_index("ix_org_idea_ledger_jaspen_score", table_name="org_idea_ledger")
    op.drop_index("ix_org_idea_ledger_industry", table_name="org_idea_ledger")
    op.drop_index("ix_org_idea_ledger_idea_category", table_name="org_idea_ledger")
    op.drop_index("ix_org_idea_ledger_source_session_id", table_name="org_idea_ledger")
    op.drop_index("ix_org_idea_ledger_originating_user_id", table_name="org_idea_ledger")
    op.drop_index("ix_org_idea_ledger_organization_id", table_name="org_idea_ledger")
    op.drop_index("ix_org_idea_ledger_ledger_id", table_name="org_idea_ledger")
    op.drop_table("org_idea_ledger")

    # user_sessions soft-delete columns
    op.drop_index("ix_user_sessions_user_archived", table_name="user_sessions")
    op.drop_index("ix_user_sessions_purge_after", table_name="user_sessions")
    op.drop_index("ix_user_sessions_archived_at", table_name="user_sessions")
    with op.batch_alter_table("user_sessions") as batch:
        batch.drop_column("purge_after")
        batch.drop_column("archived_at")
