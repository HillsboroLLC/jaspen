"""add usage_events and stripe_webhook_events tables

Revision ID: c3b7d2f9a1e4
Revises: f2a4d9c7b1e3
Create Date: 2026-05-03 13:30:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c3b7d2f9a1e4"
down_revision = "f2a4d9c7b1e3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "usage_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("thread_id", sa.String(length=255), nullable=True),
        sa.Column("model_type", sa.String(length=16), nullable=True),
        sa.Column("provider", sa.String(length=32), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("credits_charged", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_failover", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_usage_events_user_id", "usage_events", ["user_id"], unique=False)
    op.create_index("ix_usage_events_thread_id", "usage_events", ["thread_id"], unique=False)
    op.create_index("ix_usage_events_model_type", "usage_events", ["model_type"], unique=False)
    op.create_index("ix_usage_events_created_at", "usage_events", ["created_at"], unique=False)
    op.create_index("ix_usage_events_user_date", "usage_events", ["user_id", "created_at"], unique=False)

    op.create_table(
        "stripe_webhook_events",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("stripe_event_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=100), nullable=False),
        sa.Column("processed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("stripe_event_id"),
    )
    op.create_index("ix_stripe_webhook_events_stripe_event_id", "stripe_webhook_events", ["stripe_event_id"], unique=True)
    op.create_index("ix_stripe_webhook_events_event_type", "stripe_webhook_events", ["event_type"], unique=False)
    op.create_index("ix_stripe_webhook_events_processed", "stripe_webhook_events", ["processed"], unique=False)
    op.create_index("ix_stripe_webhook_events_created_at", "stripe_webhook_events", ["created_at"], unique=False)
    op.create_index("ix_stripe_webhook_events_processed_at", "stripe_webhook_events", ["processed_at"], unique=False)


def downgrade():
    op.drop_index("ix_stripe_webhook_events_processed_at", table_name="stripe_webhook_events")
    op.drop_index("ix_stripe_webhook_events_created_at", table_name="stripe_webhook_events")
    op.drop_index("ix_stripe_webhook_events_processed", table_name="stripe_webhook_events")
    op.drop_index("ix_stripe_webhook_events_event_type", table_name="stripe_webhook_events")
    op.drop_index("ix_stripe_webhook_events_stripe_event_id", table_name="stripe_webhook_events")
    op.drop_table("stripe_webhook_events")

    op.drop_index("ix_usage_events_user_date", table_name="usage_events")
    op.drop_index("ix_usage_events_created_at", table_name="usage_events")
    op.drop_index("ix_usage_events_model_type", table_name="usage_events")
    op.drop_index("ix_usage_events_thread_id", table_name="usage_events")
    op.drop_index("ix_usage_events_user_id", table_name="usage_events")
    op.drop_table("usage_events")
