"""canonical leads and email delivery

Revision ID: 1a2b3c4d5e6a
Revises: 0f4b8c2d6e91
Create Date: 2026-07-12 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "1a2b3c4d5e6a"
down_revision = "0f4b8c2d6e91"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("leads") as batch_op:
        batch_op.add_column(sa.Column("normalized_email", sa.String(length=255), nullable=True))

    op.execute("UPDATE leads SET normalized_email = lower(trim(email)) WHERE normalized_email IS NULL")

    op.create_table(
        "lead_attribution_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("source", sa.String(length=80), nullable=False),
        sa.Column("first_name", sa.String(length=120), nullable=True),
        sa.Column("last_name", sa.String(length=120), nullable=True),
        sa.Column("company", sa.String(length=160), nullable=True),
        sa.Column("title", sa.String(length=160), nullable=True),
        sa.Column("utm_source", sa.String(length=120), nullable=True),
        sa.Column("utm_medium", sa.String(length=120), nullable=True),
        sa.Column("utm_campaign", sa.String(length=160), nullable=True),
        sa.Column("referrer", sa.String(length=512), nullable=True),
        sa.Column("marketing_opt_in", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("email_delivery_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lead_attribution_events_created_at"), "lead_attribution_events", ["created_at"], unique=False)
    op.create_index(op.f("ix_lead_attribution_events_lead_id"), "lead_attribution_events", ["lead_id"], unique=False)
    op.create_index(op.f("ix_lead_attribution_events_source"), "lead_attribution_events", ["source"], unique=False)
    op.create_index("ix_lead_attribution_source_created", "lead_attribution_events", ["source", "created_at"], unique=False)

    op.execute(
        """
        INSERT INTO lead_attribution_events (
            lead_id, source, first_name, last_name, company, title,
            utm_source, utm_medium, utm_campaign, referrer,
            marketing_opt_in, email_delivery_requested, created_at
        )
        SELECT canonical.id, l.source, l.first_name, l.last_name, l.company, l.title,
            l.utm_source, l.utm_medium, l.utm_campaign, l.referrer,
            false, false, l.created_at
        FROM leads l
        JOIN (
            SELECT id, normalized_email
            FROM (
                SELECT id, normalized_email,
                    row_number() OVER (PARTITION BY normalized_email ORDER BY created_at, id) AS rn
                FROM leads
            ) ranked
            WHERE rn = 1
        ) canonical ON canonical.normalized_email = l.normalized_email
        """
    )

    op.execute(
        """
        DELETE FROM leads
        WHERE id NOT IN (
            SELECT id
            FROM (
                SELECT id,
                    row_number() OVER (PARTITION BY normalized_email ORDER BY created_at, id) AS rn
                FROM leads
            ) ranked
            WHERE rn = 1
        )
        """
    )

    with op.batch_alter_table("leads") as batch_op:
        batch_op.alter_column("normalized_email", existing_type=sa.String(length=255), nullable=False)
        batch_op.drop_constraint("uq_leads_email_source", type_="unique")
        batch_op.create_unique_constraint("uq_leads_normalized_email", ["normalized_email"])

    op.create_index(op.f("ix_leads_normalized_email"), "leads", ["normalized_email"], unique=False)

    op.create_table(
        "lead_email_deliveries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("lead_id", sa.String(length=36), nullable=False),
        sa.Column("attribution_event_id", sa.Integer(), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("email_type", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("provider_message", sa.String(length=255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["attribution_event_id"], ["lead_attribution_events.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["lead_id"], ["leads.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_lead_email_deliveries_attribution_event_id"), "lead_email_deliveries", ["attribution_event_id"], unique=False)
    op.create_index(op.f("ix_lead_email_deliveries_created_at"), "lead_email_deliveries", ["created_at"], unique=False)
    op.create_index(op.f("ix_lead_email_deliveries_email"), "lead_email_deliveries", ["email"], unique=False)
    op.create_index(op.f("ix_lead_email_deliveries_email_type"), "lead_email_deliveries", ["email_type"], unique=False)
    op.create_index(op.f("ix_lead_email_deliveries_lead_id"), "lead_email_deliveries", ["lead_id"], unique=False)
    op.create_index(op.f("ix_lead_email_deliveries_status"), "lead_email_deliveries", ["status"], unique=False)

    op.create_table(
        "email_suppressions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("normalized_email", sa.String(length=255), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False),
        sa.Column("reason", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("normalized_email", "scope", name="uq_email_suppressions_email_scope"),
    )
    op.create_index(op.f("ix_email_suppressions_created_at"), "email_suppressions", ["created_at"], unique=False)
    op.create_index(op.f("ix_email_suppressions_email"), "email_suppressions", ["email"], unique=False)
    op.create_index(op.f("ix_email_suppressions_normalized_email"), "email_suppressions", ["normalized_email"], unique=False)
    op.create_index(op.f("ix_email_suppressions_scope"), "email_suppressions", ["scope"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_email_suppressions_scope"), table_name="email_suppressions")
    op.drop_index(op.f("ix_email_suppressions_normalized_email"), table_name="email_suppressions")
    op.drop_index(op.f("ix_email_suppressions_email"), table_name="email_suppressions")
    op.drop_index(op.f("ix_email_suppressions_created_at"), table_name="email_suppressions")
    op.drop_table("email_suppressions")

    op.drop_index(op.f("ix_lead_email_deliveries_status"), table_name="lead_email_deliveries")
    op.drop_index(op.f("ix_lead_email_deliveries_lead_id"), table_name="lead_email_deliveries")
    op.drop_index(op.f("ix_lead_email_deliveries_email_type"), table_name="lead_email_deliveries")
    op.drop_index(op.f("ix_lead_email_deliveries_email"), table_name="lead_email_deliveries")
    op.drop_index(op.f("ix_lead_email_deliveries_created_at"), table_name="lead_email_deliveries")
    op.drop_index(op.f("ix_lead_email_deliveries_attribution_event_id"), table_name="lead_email_deliveries")
    op.drop_table("lead_email_deliveries")

    op.drop_index(op.f("ix_leads_normalized_email"), table_name="leads")
    with op.batch_alter_table("leads") as batch_op:
        batch_op.drop_constraint("uq_leads_normalized_email", type_="unique")
        batch_op.create_unique_constraint("uq_leads_email_source", ["email", "source"])
        batch_op.drop_column("normalized_email")

    op.drop_index("ix_lead_attribution_source_created", table_name="lead_attribution_events")
    op.drop_index(op.f("ix_lead_attribution_events_source"), table_name="lead_attribution_events")
    op.drop_index(op.f("ix_lead_attribution_events_lead_id"), table_name="lead_attribution_events")
    op.drop_index(op.f("ix_lead_attribution_events_created_at"), table_name="lead_attribution_events")
    op.drop_table("lead_attribution_events")
