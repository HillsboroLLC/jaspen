"""add lead decision profiles

Revision ID: 2b3c4d5e6f7a
Revises: 1a2b3c4d5e6a
Create Date: 2026-07-12 13:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "2b3c4d5e6f7a"
down_revision = "1a2b3c4d5e6a"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "lead_decision_profiles",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("attribution_event_id", sa.Integer(), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("normalized_email", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False, server_default="decision-style-assessment"),
        sa.Column("answers", sa.JSON(), nullable=False),
        sa.Column("client_style_key", sa.String(length=80), nullable=True),
        sa.Column("verified_style_key", sa.String(length=80), nullable=False),
        sa.Column("style_name", sa.String(length=120), nullable=False),
        sa.Column("is_fallback", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("affinity", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["attribution_event_id"], ["lead_attribution_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_lead_decision_profiles_attribution_event_id", "lead_decision_profiles", ["attribution_event_id"])
    op.create_index("ix_lead_decision_profiles_created_at", "lead_decision_profiles", ["created_at"])
    op.create_index("ix_lead_decision_profiles_email", "lead_decision_profiles", ["email"])
    op.create_index("ix_lead_decision_profiles_lead_id", "lead_decision_profiles", ["lead_id"])
    op.create_index("ix_lead_decision_profiles_normalized_email", "lead_decision_profiles", ["normalized_email"])
    op.create_index("ix_lead_decision_profiles_source", "lead_decision_profiles", ["source"])
    op.create_index("ix_lead_decision_profiles_verified_style_key", "lead_decision_profiles", ["verified_style_key"])


def downgrade():
    op.drop_index("ix_lead_decision_profiles_verified_style_key", table_name="lead_decision_profiles")
    op.drop_index("ix_lead_decision_profiles_source", table_name="lead_decision_profiles")
    op.drop_index("ix_lead_decision_profiles_normalized_email", table_name="lead_decision_profiles")
    op.drop_index("ix_lead_decision_profiles_lead_id", table_name="lead_decision_profiles")
    op.drop_index("ix_lead_decision_profiles_email", table_name="lead_decision_profiles")
    op.drop_index("ix_lead_decision_profiles_created_at", table_name="lead_decision_profiles")
    op.drop_index("ix_lead_decision_profiles_attribution_event_id", table_name="lead_decision_profiles")
    op.drop_table("lead_decision_profiles")
