"""Rename the self-service Enterprise plan key to Business.

Revision ID: f8d5c3b0e2a7
Revises: e7c4b2a9d1f6
"""

from alembic import op


revision = "f8d5c3b0e2a7"
down_revision = "e7c4b2a9d1f6"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE users SET subscription_plan = 'business' "
        "WHERE LOWER(COALESCE(subscription_plan, '')) = 'enterprise'"
    )
    op.execute(
        "UPDATE organizations SET plan_key = 'business', max_admin_seats = 5, "
        "max_total_paid_seats = 10 "
        "WHERE LOWER(COALESCE(plan_key, '')) = 'enterprise'"
    )


def downgrade():
    op.execute(
        "UPDATE users SET subscription_plan = 'enterprise' "
        "WHERE LOWER(COALESCE(subscription_plan, '')) = 'business'"
    )
    op.execute(
        "UPDATE organizations SET plan_key = 'enterprise' "
        "WHERE LOWER(COALESCE(plan_key, '')) = 'business'"
    )
