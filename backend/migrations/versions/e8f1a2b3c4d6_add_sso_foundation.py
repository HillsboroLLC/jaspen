"""Add the disabled-by-default enterprise SSO foundation.

Revision ID: e8f1a2b3c4d6
Revises: d4e6f8a0b2c3
"""

from alembic import op
import sqlalchemy as sa


revision = "e8f1a2b3c4d6"
down_revision = "d4e6f8a0b2c3"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("organizations") as batch:
        batch.add_column(sa.Column("workos_organization_id", sa.String(255), nullable=True))
        batch.add_column(sa.Column("sso_status", sa.String(32), nullable=False, server_default="off"))
        batch.add_column(sa.Column("sso_enforced", sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column("sso_enforced_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("sso_grace_until", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("sso_mfa_attested_by", sa.String(36), nullable=True))
        batch.add_column(sa.Column("sso_mfa_attested_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("sso_recovery_admin_user_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("sso_sessions_revoked_at", sa.DateTime(), nullable=True))
        batch.create_foreign_key("fk_org_sso_mfa_attested_by", "users", ["sso_mfa_attested_by"], ["id"], ondelete="SET NULL")
        batch.create_foreign_key("fk_org_sso_recovery_admin", "users", ["sso_recovery_admin_user_id"], ["id"], ondelete="SET NULL")
        batch.create_unique_constraint("uq_organizations_workos_organization_id", ["workos_organization_id"])
        batch.create_index("ix_organizations_workos_organization_id", ["workos_organization_id"])
        batch.create_index("ix_organizations_sso_status", ["sso_status"])

    with op.batch_alter_table("user_auth_sessions") as batch:
        batch.add_column(sa.Column("auth_method", sa.String(32), nullable=True))
        batch.add_column(sa.Column("sso_organization_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("authenticated_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("last_activity_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_user_auth_sessions_auth_method", ["auth_method"])
        batch.create_index("ix_user_auth_sessions_sso_organization_id", ["sso_organization_id"])

    op.create_table(
        "sso_identities",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False, server_default="workos"),
        sa.Column("provider_identity_id", sa.String(255), nullable=False),
        sa.Column("connection_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("organization_id", "provider", "provider_identity_id", name="uq_sso_identity_provider"),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_sso_identity_org_user"),
    )
    op.create_index("ix_sso_identities_user_id", "sso_identities", ["user_id"])
    op.create_index("ix_sso_identities_organization_id", "sso_identities", ["organization_id"])

    op.create_table(
        "sso_login_states",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("next_path", sa.String(512), nullable=False, server_default="/new"),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_sso_login_states_state_hash", "sso_login_states", ["state_hash"], unique=True)
    op.create_index("ix_sso_login_states_organization_id", "sso_login_states", ["organization_id"])
    op.create_index("ix_sso_login_states_expires_at", "sso_login_states", ["expires_at"])
    op.create_index("ix_sso_login_states_used_at", "sso_login_states", ["used_at"])


def downgrade():
    op.drop_table("sso_login_states")
    op.drop_table("sso_identities")
    with op.batch_alter_table("user_auth_sessions") as batch:
        batch.drop_index("ix_user_auth_sessions_sso_organization_id")
        batch.drop_index("ix_user_auth_sessions_auth_method")
        batch.drop_column("last_activity_at")
        batch.drop_column("authenticated_at")
        batch.drop_column("sso_organization_id")
        batch.drop_column("auth_method")
    with op.batch_alter_table("organizations") as batch:
        batch.drop_index("ix_organizations_sso_status")
        batch.drop_index("ix_organizations_workos_organization_id")
        batch.drop_constraint("uq_organizations_workos_organization_id", type_="unique")
        batch.drop_constraint("fk_org_sso_recovery_admin", type_="foreignkey")
        batch.drop_constraint("fk_org_sso_mfa_attested_by", type_="foreignkey")
        batch.drop_column("sso_sessions_revoked_at")
        batch.drop_column("sso_recovery_admin_user_id")
        batch.drop_column("sso_mfa_attested_at")
        batch.drop_column("sso_mfa_attested_by")
        batch.drop_column("sso_grace_until")
        batch.drop_column("sso_enforced_at")
        batch.drop_column("sso_enforced")
        batch.drop_column("sso_status")
        batch.drop_column("workos_organization_id")
