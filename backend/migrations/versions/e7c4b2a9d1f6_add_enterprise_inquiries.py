"""add enterprise investment calculator inquiries

Revision ID: e7c4b2a9d1f6
Revises: a1b2c3d4e5f6
"""
from alembic import op
import sqlalchemy as sa

revision = "e7c4b2a9d1f6"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "enterprise_inquiries",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("attribution_event_id", sa.Integer(), nullable=True),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("preferred_contact", sa.String(length=20), nullable=True),
        sa.Column("comments", sa.Text(), nullable=True),
        sa.Column("participants", sa.Integer(), nullable=False),
        sa.Column("teams", sa.Integer(), nullable=False),
        sa.Column("usage", sa.String(length=20), nullable=False),
        sa.Column("requirements_json", sa.Text(), nullable=False),
        sa.Column("hourly_cost", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("recommendation", sa.String(length=80), nullable=False),
        sa.Column("annual_low", sa.Integer(), nullable=True),
        sa.Column("annual_high", sa.Integer(), nullable=True),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["attribution_event_id"], ["lead_attribution_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_enterprise_inquiries_lead_id", "enterprise_inquiries", ["lead_id"])
    op.create_index("ix_enterprise_inquiries_attribution_event_id", "enterprise_inquiries", ["attribution_event_id"])
    op.create_index("ix_enterprise_inquiries_created_at", "enterprise_inquiries", ["created_at"])


def downgrade():
    op.drop_index("ix_enterprise_inquiries_created_at", table_name="enterprise_inquiries")
    op.drop_index("ix_enterprise_inquiries_attribution_event_id", table_name="enterprise_inquiries")
    op.drop_index("ix_enterprise_inquiries_lead_id", table_name="enterprise_inquiries")
    op.drop_table("enterprise_inquiries")
