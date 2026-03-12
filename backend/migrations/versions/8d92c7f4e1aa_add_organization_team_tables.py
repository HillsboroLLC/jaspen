"""add organization/team tables and org-scoped session metadata

Revision ID: 8d92c7f4e1aa
Revises: 3f21f8b9a4de
Create Date: 2026-03-12 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "8d92c7f4e1aa"
down_revision = "3f21f8b9a4de"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "organizations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("slug", sa.String(length=128), nullable=True),
        sa.Column("owner_user_id", sa.String(length=36), nullable=True),
        sa.Column("plan_key", sa.String(length=50), nullable=False, server_default="free"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_organizations_slug"),
    )
    op.create_index("ix_organizations_owner_user_id", "organizations", ["owner_user_id"], unique=False)
    op.create_index("ix_organizations_plan_key", "organizations", ["plan_key"], unique=False)

    op.create_table(
        "organization_members",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="viewer"),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="active"),
        sa.Column("invited_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("joined_at", sa.DateTime(), nullable=True),
        sa.Column("last_active_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("organization_id", "user_id", name="uq_org_members_organization_user"),
    )
    op.create_index("ix_organization_members_organization_id", "organization_members", ["organization_id"], unique=False)
    op.create_index("ix_organization_members_user_id", "organization_members", ["user_id"], unique=False)
    op.create_index("ix_organization_members_role", "organization_members", ["role"], unique=False)
    op.create_index("ix_organization_members_status", "organization_members", ["status"], unique=False)
    op.create_index("ix_organization_members_invited_by_user_id", "organization_members", ["invited_by_user_id"], unique=False)

    op.create_table(
        "organization_invitations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=False, server_default="viewer"),
        sa.Column("token", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
        sa.Column("invited_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("accepted_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["invited_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["accepted_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token", name="uq_organization_invitations_token"),
    )
    op.create_index("ix_organization_invitations_organization_id", "organization_invitations", ["organization_id"], unique=False)
    op.create_index("ix_organization_invitations_email", "organization_invitations", ["email"], unique=False)
    op.create_index("ix_organization_invitations_status", "organization_invitations", ["status"], unique=False)
    op.create_index("ix_organization_invitations_expires_at", "organization_invitations", ["expires_at"], unique=False)
    op.create_index("ix_organization_invitations_invited_by_user_id", "organization_invitations", ["invited_by_user_id"], unique=False)
    op.create_index("ix_organization_invitations_accepted_by_user_id", "organization_invitations", ["accepted_by_user_id"], unique=False)
    op.create_index("ix_organization_invitations_token", "organization_invitations", ["token"], unique=True)

    op.add_column("users", sa.Column("active_organization_id", sa.String(length=36), nullable=True))
    op.create_index("ix_users_active_organization_id", "users", ["active_organization_id"], unique=False)
    op.create_foreign_key(
        "fk_users_active_organization_id",
        "users",
        "organizations",
        ["active_organization_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column("user_sessions", sa.Column("organization_id", sa.String(length=36), nullable=True))
    op.add_column("user_sessions", sa.Column("created_by_user_id", sa.String(length=36), nullable=True))
    op.add_column("user_sessions", sa.Column("visibility", sa.String(length=32), nullable=False, server_default="private"))
    op.add_column("user_sessions", sa.Column("shared_with_user_ids", sa.JSON(), nullable=True))
    op.create_index("ix_user_sessions_organization_id", "user_sessions", ["organization_id"], unique=False)
    op.create_index("ix_user_sessions_created_by_user_id", "user_sessions", ["created_by_user_id"], unique=False)
    op.create_index("ix_user_sessions_visibility", "user_sessions", ["visibility"], unique=False)
    op.create_foreign_key(
        "fk_user_sessions_organization_id",
        "user_sessions",
        "organizations",
        ["organization_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_user_sessions_created_by_user_id",
        "user_sessions",
        "users",
        ["created_by_user_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade():
    op.drop_constraint("fk_user_sessions_created_by_user_id", "user_sessions", type_="foreignkey")
    op.drop_constraint("fk_user_sessions_organization_id", "user_sessions", type_="foreignkey")
    op.drop_index("ix_user_sessions_visibility", table_name="user_sessions")
    op.drop_index("ix_user_sessions_created_by_user_id", table_name="user_sessions")
    op.drop_index("ix_user_sessions_organization_id", table_name="user_sessions")
    op.drop_column("user_sessions", "shared_with_user_ids")
    op.drop_column("user_sessions", "visibility")
    op.drop_column("user_sessions", "created_by_user_id")
    op.drop_column("user_sessions", "organization_id")

    op.drop_constraint("fk_users_active_organization_id", "users", type_="foreignkey")
    op.drop_index("ix_users_active_organization_id", table_name="users")
    op.drop_column("users", "active_organization_id")

    op.drop_index("ix_organization_invitations_token", table_name="organization_invitations")
    op.drop_index("ix_organization_invitations_accepted_by_user_id", table_name="organization_invitations")
    op.drop_index("ix_organization_invitations_invited_by_user_id", table_name="organization_invitations")
    op.drop_index("ix_organization_invitations_expires_at", table_name="organization_invitations")
    op.drop_index("ix_organization_invitations_status", table_name="organization_invitations")
    op.drop_index("ix_organization_invitations_email", table_name="organization_invitations")
    op.drop_index("ix_organization_invitations_organization_id", table_name="organization_invitations")
    op.drop_table("organization_invitations")

    op.drop_index("ix_organization_members_invited_by_user_id", table_name="organization_members")
    op.drop_index("ix_organization_members_status", table_name="organization_members")
    op.drop_index("ix_organization_members_role", table_name="organization_members")
    op.drop_index("ix_organization_members_user_id", table_name="organization_members")
    op.drop_index("ix_organization_members_organization_id", table_name="organization_members")
    op.drop_table("organization_members")

    op.drop_index("ix_organizations_plan_key", table_name="organizations")
    op.drop_index("ix_organizations_owner_user_id", table_name="organizations")
    op.drop_table("organizations")
