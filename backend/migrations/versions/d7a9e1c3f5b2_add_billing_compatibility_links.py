"""Add inactive nullable billing compatibility links.

Revision ID: d7a9e1c3f5b2
Revises: c6f8d0b2e4a1

Phase 2.3 adds nullable, indexed foreign keys only. It does not populate or
read the links and changes no current billing or AI behavior.
"""

from alembic import op
import sqlalchemy as sa


revision = "d7a9e1c3f5b2"
down_revision = "c6f8d0b2e4a1"
branch_labels = None
depends_on = None


COMPATIBILITY_LINKS = (
    ("ai_operations", "billing_account_id"),
    ("ai_operations", "pricing_policy_version_id"),
    ("ai_operations", "capacity_policy_version_id"),
    ("payments", "billing_account_id"),
)


class CompatibilityLinksNotEmptyError(RuntimeError):
    """Raised when downgrade would discard a populated compatibility link."""


def upgrade():
    op.add_column(
        "ai_operations",
        sa.Column("billing_account_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "ai_operations",
        sa.Column("pricing_policy_version_id", sa.String(36), nullable=True),
    )
    op.add_column(
        "ai_operations",
        sa.Column("capacity_policy_version_id", sa.String(36), nullable=True),
    )
    with op.batch_alter_table("ai_operations") as batch_op:
        batch_op.create_foreign_key(
            "fk_ai_operations_billing_account_id",
            "billing_accounts",
            ["billing_account_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_ai_operations_pricing_policy_version_id",
            "pricing_policy_versions",
            ["pricing_policy_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_foreign_key(
            "fk_ai_operations_capacity_policy_version_id",
            "capacity_policy_versions",
            ["capacity_policy_version_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "ix_ai_operations_billing_account_id",
        "ai_operations",
        ["billing_account_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_operations_pricing_policy_version_id",
        "ai_operations",
        ["pricing_policy_version_id"],
        unique=False,
    )
    op.create_index(
        "ix_ai_operations_capacity_policy_version_id",
        "ai_operations",
        ["capacity_policy_version_id"],
        unique=False,
    )

    op.add_column(
        "payments",
        sa.Column("billing_account_id", sa.String(36), nullable=True),
    )
    with op.batch_alter_table("payments") as batch_op:
        batch_op.create_foreign_key(
            "fk_payments_billing_account_id",
            "billing_accounts",
            ["billing_account_id"],
            ["id"],
            ondelete="RESTRICT",
        )
    op.create_index(
        "ix_payments_billing_account_id",
        "payments",
        ["billing_account_id"],
        unique=False,
    )


def downgrade():
    """Remove only unused compatibility links."""
    bind = op.get_bind()
    populated = []
    for table, column in COMPATIBILITY_LINKS:
        count = bind.execute(
            sa.text(f"SELECT COUNT(*) FROM {table} WHERE {column} IS NOT NULL")
        ).scalar() or 0
        if count:
            populated.append(f"{table}.{column}={count}")

    if populated:
        raise CompatibilityLinksNotEmptyError(
            f"Cannot downgrade {revision}: {', '.join(populated)}. Phase 2.3 "
            "downgrade may remove only unused compatibility links."
        )

    with op.batch_alter_table("payments") as batch_op:
        batch_op.drop_index("ix_payments_billing_account_id")
        batch_op.drop_constraint(
            "fk_payments_billing_account_id",
            type_="foreignkey",
        )
        batch_op.drop_column("billing_account_id")

    with op.batch_alter_table("ai_operations") as batch_op:
        batch_op.drop_index("ix_ai_operations_capacity_policy_version_id")
        batch_op.drop_index("ix_ai_operations_pricing_policy_version_id")
        batch_op.drop_index("ix_ai_operations_billing_account_id")
        batch_op.drop_constraint(
            "fk_ai_operations_capacity_policy_version_id",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_ai_operations_pricing_policy_version_id",
            type_="foreignkey",
        )
        batch_op.drop_constraint(
            "fk_ai_operations_billing_account_id",
            type_="foreignkey",
        )
        batch_op.drop_column("capacity_policy_version_id")
        batch_op.drop_column("pricing_policy_version_id")
        batch_op.drop_column("billing_account_id")
