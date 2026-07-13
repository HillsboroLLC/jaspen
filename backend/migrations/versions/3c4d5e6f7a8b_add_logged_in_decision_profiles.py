"""add logged-in decision profiles

Revision ID: 3c4d5e6f7a8b
Revises: 2b3c4d5e6f7a
Create Date: 2026-07-13 00:44:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "3c4d5e6f7a8b"
down_revision = "2b3c4d5e6f7a"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("lead_decision_profiles") as batch:
        batch.add_column(sa.Column("user_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("completed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
        batch.add_column(sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()))
        batch.add_column(sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
        batch.add_column(sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.create_foreign_key(
            "fk_lead_decision_profiles_user_id_users",
            "users",
            ["user_id"],
            ["id"],
            ondelete="SET NULL",
        )

    op.create_index("ix_lead_decision_profiles_user_id", "lead_decision_profiles", ["user_id"])
    op.create_index("ix_lead_decision_profiles_completed_at", "lead_decision_profiles", ["completed_at"])
    op.create_index("ix_lead_decision_profiles_is_current", "lead_decision_profiles", ["is_current"])
    op.create_index(
        "ix_lead_decision_profiles_user_current",
        "lead_decision_profiles",
        ["user_id", "is_current"],
    )
    op.create_index(
        "ix_lead_decision_profiles_email_current",
        "lead_decision_profiles",
        ["normalized_email", "is_current"],
    )

    op.create_table(
        "lead_decision_profile_responses",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("decision_profile_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.String(length=80), nullable=False),
        sa.Column("answer_id", sa.String(length=80), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("tendency", sa.String(length=120), nullable=False),
        sa.Column("answer_label", sa.String(length=255), nullable=False),
        sa.Column("meaning", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["decision_profile_id"], ["lead_decision_profiles.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("decision_profile_id", "question_id", name="uq_decision_profile_response_question"),
    )
    op.create_index(
        "ix_lead_decision_profile_responses_decision_profile_id",
        "lead_decision_profile_responses",
        ["decision_profile_id"],
    )
    op.create_index(
        "ix_lead_decision_profile_responses_created_at",
        "lead_decision_profile_responses",
        ["created_at"],
    )


def downgrade():
    op.drop_index("ix_lead_decision_profile_responses_created_at", table_name="lead_decision_profile_responses")
    op.drop_index("ix_lead_decision_profile_responses_decision_profile_id", table_name="lead_decision_profile_responses")
    op.drop_table("lead_decision_profile_responses")

    op.drop_index("ix_lead_decision_profiles_email_current", table_name="lead_decision_profiles")
    op.drop_index("ix_lead_decision_profiles_user_current", table_name="lead_decision_profiles")
    op.drop_index("ix_lead_decision_profiles_is_current", table_name="lead_decision_profiles")
    op.drop_index("ix_lead_decision_profiles_completed_at", table_name="lead_decision_profiles")
    op.drop_index("ix_lead_decision_profiles_user_id", table_name="lead_decision_profiles")
    with op.batch_alter_table("lead_decision_profiles") as batch:
        batch.drop_constraint("fk_lead_decision_profiles_user_id_users", type_="foreignkey")
        batch.drop_column("is_current")
        batch.drop_column("version")
        batch.drop_column("updated_at")
        batch.drop_column("completed_at")
        batch.drop_column("user_id")
