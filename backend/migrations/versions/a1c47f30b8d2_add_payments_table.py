"""Add payments table recording money actually received.

Revision ID: a1c47f30b8d2
Revises: 374bcfa9f423
Create Date: 2026-08-03 12:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "a1c47f30b8d2"
down_revision = "374bcfa9f423"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "payments" in inspector.get_table_names():
        return

    op.create_table(
        "payments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("external_reference", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("amount_paid_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("amount_due_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("discount_cents", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="usd"),
        sa.Column("is_comped", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("promotion_code", sa.String(length=120), nullable=True),
        sa.Column("plan_key", sa.String(length=40), nullable=True),
        sa.Column("billing_interval", sa.String(length=10), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(length=255), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("external_reference", name="uq_payments_external_reference"),
    )

    op.create_index("ix_payments_user_id", "payments", ["user_id"])
    op.create_index("ix_payments_organization_id", "payments", ["organization_id"])
    op.create_index("ix_payments_external_reference", "payments", ["external_reference"])
    op.create_index("ix_payments_source", "payments", ["source"])
    op.create_index("ix_payments_is_comped", "payments", ["is_comped"])
    op.create_index("ix_payments_plan_key", "payments", ["plan_key"])
    op.create_index("ix_payments_stripe_subscription_id", "payments", ["stripe_subscription_id"])
    op.create_index("ix_payments_paid_at", "payments", ["paid_at"])
    # Serves the dashboard's "paid, in window" scan without touching the table.
    op.create_index("ix_payments_paid_at_amount", "payments", ["paid_at", "amount_paid_cents"])


def downgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "payments" not in inspector.get_table_names():
        return
    op.drop_table("payments")
