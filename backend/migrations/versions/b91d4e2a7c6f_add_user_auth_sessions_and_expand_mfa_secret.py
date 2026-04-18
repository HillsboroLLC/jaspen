"""add user_auth_sessions and expand mfa_secret length

Revision ID: b91d4e2a7c6f
Revises: ('6b8c1d2e3f4a', '9a6f2c4b8d1e')
Create Date: 2026-04-18 18:25:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "b91d4e2a7c6f"
down_revision = ("6b8c1d2e3f4a", "9a6f2c4b8d1e")
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "mfa_secret",
            existing_type=sa.String(length=64),
            type_=sa.String(length=512),
            existing_nullable=True,
        )

    op.create_table(
        "user_auth_sessions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("token_jti", sa.String(length=128), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("issued_at", sa.DateTime(), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("ip_address", sa.String(length=128), nullable=True),
        sa.Column("user_agent", sa.String(length=512), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_jti"),
    )
    op.create_index("ix_user_auth_sessions_user_id", "user_auth_sessions", ["user_id"], unique=False)
    op.create_index("ix_user_auth_sessions_token_jti", "user_auth_sessions", ["token_jti"], unique=False)
    op.create_index("ix_user_auth_sessions_organization_id", "user_auth_sessions", ["organization_id"], unique=False)
    op.create_index("ix_user_auth_sessions_issued_at", "user_auth_sessions", ["issued_at"], unique=False)
    op.create_index("ix_user_auth_sessions_expires_at", "user_auth_sessions", ["expires_at"], unique=False)
    op.create_index("ix_user_auth_sessions_revoked_at", "user_auth_sessions", ["revoked_at"], unique=False)
    op.create_index(
        "ix_user_auth_sessions_user_revoked",
        "user_auth_sessions",
        ["user_id", "revoked_at"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_user_auth_sessions_user_revoked", table_name="user_auth_sessions")
    op.drop_index("ix_user_auth_sessions_revoked_at", table_name="user_auth_sessions")
    op.drop_index("ix_user_auth_sessions_expires_at", table_name="user_auth_sessions")
    op.drop_index("ix_user_auth_sessions_issued_at", table_name="user_auth_sessions")
    op.drop_index("ix_user_auth_sessions_organization_id", table_name="user_auth_sessions")
    op.drop_index("ix_user_auth_sessions_token_jti", table_name="user_auth_sessions")
    op.drop_index("ix_user_auth_sessions_user_id", table_name="user_auth_sessions")
    op.drop_table("user_auth_sessions")

    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.alter_column(
            "mfa_secret",
            existing_type=sa.String(length=512),
            type_=sa.String(length=64),
            existing_nullable=True,
        )

