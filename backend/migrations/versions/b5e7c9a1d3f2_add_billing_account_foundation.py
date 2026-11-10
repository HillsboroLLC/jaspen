"""Add the empty organization-first billing account foundation.

Revision ID: b5e7c9a1d3f2
Revises: a4d7c9e2f105

Phase 2.1 is schema-only.  It creates no billing account or role row and does
not connect the new tables to any runtime reader or writer.
"""

from alembic import op
import sqlalchemy as sa


revision = "b5e7c9a1d3f2"
down_revision = "a4d7c9e2f105"
branch_labels = None
depends_on = None


class BillingFoundationNotEmptyError(RuntimeError):
    """Raised when a destructive downgrade would discard billing evidence."""


def upgrade():
    op.create_table(
        "billing_accounts",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column(
            "status",
            sa.String(24),
            nullable=False,
            server_default="proposed",
        ),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("account_anchor_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processor", sa.String(32), nullable=True),
        sa.Column("processor_customer_id", sa.String(255), nullable=True),
        sa.Column("tax_context_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('proposed', 'active', 'restricted', 'closed')",
            name="ck_billing_accounts_status",
        ),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = lower(currency) AND "
            "substr(currency, 1, 1) BETWEEN 'a' AND 'z' AND "
            "substr(currency, 2, 1) BETWEEN 'a' AND 'z' AND "
            "substr(currency, 3, 1) BETWEEN 'a' AND 'z'",
            name="ck_billing_accounts_currency",
        ),
        sa.CheckConstraint(
            "((processor IS NULL AND processor_customer_id IS NULL) OR "
            "(processor IS NOT NULL AND processor_customer_id IS NOT NULL))",
            name="ck_billing_accounts_processor_identity",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name="fk_billing_accounts_organization_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_billing_accounts"),
        sa.UniqueConstraint(
            "organization_id",
            name="uq_billing_accounts_organization_id",
        ),
    )
    op.create_index(
        "uq_billing_accounts_processor_customer",
        "billing_accounts",
        ["processor", "processor_customer_id"],
        unique=True,
        postgresql_where=sa.text("processor_customer_id IS NOT NULL"),
        sqlite_where=sa.text("processor_customer_id IS NOT NULL"),
    )
    op.create_index(
        "ix_billing_accounts_status_created_at",
        "billing_accounts",
        ["status", "created_at"],
        unique=False,
    )

    op.create_table(
        "billing_role_grants",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column(
            "state",
            sa.String(16),
            nullable=False,
            server_default="active",
        ),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("granted_by_user_id", sa.String(36), nullable=True),
        sa.Column("origin_type", sa.String(40), nullable=False),
        sa.Column("origin_id", sa.String(255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "role IN ('billing_owner', 'billing_admin', 'billing_viewer')",
            name="ck_billing_role_grants_role",
        ),
        sa.CheckConstraint(
            "state IN ('active', 'revoked', 'expired')",
            name="ck_billing_role_grants_state",
        ),
        sa.CheckConstraint(
            "ends_at IS NULL OR ends_at > starts_at",
            name="ck_billing_role_grants_interval",
        ),
        sa.ForeignKeyConstraint(
            ["billing_account_id"],
            ["billing_accounts.id"],
            name="fk_billing_role_grants_billing_account_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_billing_role_grants_user_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["granted_by_user_id"],
            ["users.id"],
            name="fk_billing_role_grants_granted_by_user_id",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_billing_role_grants"),
        sa.UniqueConstraint(
            "billing_account_id",
            "user_id",
            "role",
            "starts_at",
            name="uq_billing_role_grants_account_user_role_start",
        ),
    )
    op.create_index(
        "uq_billing_role_grants_open_role",
        "billing_role_grants",
        ["billing_account_id", "user_id", "role"],
        unique=True,
        postgresql_where=sa.text("state = 'active' AND ends_at IS NULL"),
        sqlite_where=sa.text("state = 'active' AND ends_at IS NULL"),
    )
    op.create_index(
        "ix_billing_role_grants_account_state",
        "billing_role_grants",
        ["billing_account_id", "state"],
        unique=False,
    )
    op.create_index(
        "ix_billing_role_grants_user_state",
        "billing_role_grants",
        ["user_id", "state"],
        unique=False,
    )


def downgrade():
    """Drop the foundation only while both tables are still empty."""
    bind = op.get_bind()
    account_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM billing_accounts")
    ).scalar() or 0
    role_count = bind.execute(
        sa.text("SELECT COUNT(*) FROM billing_role_grants")
    ).scalar() or 0

    if account_count or role_count:
        raise BillingFoundationNotEmptyError(
            f"Cannot downgrade {revision}: billing_accounts contains "
            f"{account_count} row(s) and billing_role_grants contains "
            f"{role_count} row(s). Phase 2.1 downgrade may remove only empty "
            "foundation tables; it will not discard billing identity or "
            "permission evidence."
        )

    op.drop_index(
        "ix_billing_role_grants_user_state",
        table_name="billing_role_grants",
    )
    op.drop_index(
        "ix_billing_role_grants_account_state",
        table_name="billing_role_grants",
    )
    op.drop_index(
        "uq_billing_role_grants_open_role",
        table_name="billing_role_grants",
    )
    op.drop_table("billing_role_grants")

    op.drop_index(
        "ix_billing_accounts_status_created_at",
        table_name="billing_accounts",
    )
    op.drop_index(
        "uq_billing_accounts_processor_customer",
        table_name="billing_accounts",
    )
    op.drop_table("billing_accounts")
