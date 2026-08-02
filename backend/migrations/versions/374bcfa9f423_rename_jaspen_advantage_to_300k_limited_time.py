"""Rename the Jaspen Advantage entitlement/credit source key to 300K Limited-Time.

Revision ID: 374bcfa9f423
Revises: 8c4e2a1d7f90
"""

from alembic import op


revision = "374bcfa9f423"
down_revision = "8c4e2a1d7f90"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "UPDATE account_entitlements SET entitlement_key = '300k_limited_time' "
        "WHERE entitlement_key = 'jaspen_advantage'"
    )
    op.execute(
        "UPDATE persistent_credit_grants SET source = '300k_limited_time' "
        "WHERE source = 'jaspen_advantage'"
    )


def downgrade():
    op.execute(
        "UPDATE account_entitlements SET entitlement_key = 'jaspen_advantage' "
        "WHERE entitlement_key = '300k_limited_time'"
    )
    op.execute(
        "UPDATE persistent_credit_grants SET source = 'jaspen_advantage' "
        "WHERE source = '300k_limited_time'"
    )
