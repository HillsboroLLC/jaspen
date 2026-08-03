"""Add advisory_inquiries for Executive Partnership Requests.

Revision ID: b7e2d91a4c03
Revises: a1c47f30b8d2
Create Date: 2026-08-03 18:05:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "b7e2d91a4c03"
down_revision = "a1c47f30b8d2"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "advisory_inquiries" in inspector.get_table_names():
        return

    op.create_table(
        "advisory_inquiries",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("attribution_event_id", sa.Integer(), nullable=True),
        sa.Column("engagement", sa.String(length=40), nullable=False),
        sa.Column("phone", sa.String(length=40), nullable=True),
        sa.Column("decision_description", sa.Text(), nullable=False),
        sa.Column("desired_outcome", sa.Text(), nullable=False),
        sa.Column("financial_impact_band", sa.String(length=40), nullable=True),
        sa.Column("decision_timeline", sa.String(length=40), nullable=False),
        sa.Column("participants_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("decision_authority", sa.String(length=40), nullable=False),
        sa.Column("additional_notes", sa.Text(), nullable=True),
        sa.Column("source_url", sa.String(length=1024), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["attribution_event_id"], ["lead_attribution_events.id"], ondelete="SET NULL"
        ),
    )

    op.create_index("ix_advisory_inquiries_lead_id", "advisory_inquiries", ["lead_id"])
    op.create_index("ix_advisory_inquiries_attribution_event_id", "advisory_inquiries", ["attribution_event_id"])
    op.create_index("ix_advisory_inquiries_engagement", "advisory_inquiries", ["engagement"])
    op.create_index("ix_advisory_inquiries_financial_impact_band", "advisory_inquiries", ["financial_impact_band"])
    op.create_index("ix_advisory_inquiries_decision_timeline", "advisory_inquiries", ["decision_timeline"])
    op.create_index("ix_advisory_inquiries_created_at", "advisory_inquiries", ["created_at"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "advisory_inquiries" not in inspector.get_table_names():
        return
    op.drop_table("advisory_inquiries")
