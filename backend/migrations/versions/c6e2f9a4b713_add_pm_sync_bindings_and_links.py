"""add plan-scoped PM sync bindings and links

Revision ID: c6e2f9a4b713
Revises: b3e8f1c5a902
Create Date: 2026-10-11
"""
from alembic import op
import sqlalchemy as sa

revision = "c6e2f9a4b713"
down_revision = "b3e8f1c5a902"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "pm_sync_bindings",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=True),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("plan_key", sa.String(64), nullable=False),
        sa.Column("connector_id", sa.String(32), nullable=False),
        sa.Column("external_container_id", sa.String(255), nullable=False),
        sa.Column("external_container_url", sa.Text(), nullable=True),
        sa.Column("mode", sa.String(32), nullable=False),
        sa.Column("conflict_policy", sa.String(32), nullable=False),
        sa.Column("field_policy_overrides", sa.JSON(), nullable=False),
        sa.Column("policy_set_by_user_id", sa.String(36), nullable=True),
        sa.Column("policy_set_at", sa.DateTime(), nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("user_map", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("poll_cursor", sa.String(255), nullable=True),
        sa.Column("last_pull_at", sa.DateTime(), nullable=True),
        sa.Column("last_push_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("lock_until", sa.DateTime(), nullable=True),
        sa.Column("failure_count", sa.Integer(), nullable=False),
        sa.Column("next_retry_at", sa.DateTime(), nullable=True),
        sa.Column("webhook_token_hash", sa.String(128), nullable=True),
        sa.Column("external_webhook_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["policy_set_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thread_id", "plan_key", "connector_id", name="uq_pm_sync_binding_plan_connector"),
    )
    op.create_index("ix_pm_sync_bindings_user_id", "pm_sync_bindings", ["user_id"])
    op.create_index("ix_pm_sync_bindings_organization_id", "pm_sync_bindings", ["organization_id"])
    op.create_index("ix_pm_sync_bindings_thread_id", "pm_sync_bindings", ["thread_id"])

    op.create_table(
        "pm_sync_links",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("binding_id", sa.String(36), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("jaspen_id", sa.String(255), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("external_parent_id", sa.String(255), nullable=True),
        sa.Column("base_snapshot", sa.JSON(), nullable=False),
        sa.Column("external_version", sa.String(255), nullable=True),
        sa.Column("jaspen_version", sa.String(255), nullable=True),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["binding_id"], ["pm_sync_bindings.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("binding_id", "entity_type", "jaspen_id", name="uq_pm_sync_link_jaspen_entity"),
        sa.UniqueConstraint("binding_id", "external_id", name="uq_pm_sync_link_external"),
    )
    op.create_index("ix_pm_sync_links_binding_id", "pm_sync_links", ["binding_id"])
    op.add_column("connector_sync_logs", sa.Column("sync_metadata", sa.JSON(), nullable=True))


def downgrade():
    op.drop_column("connector_sync_logs", "sync_metadata")
    op.drop_index("ix_pm_sync_links_binding_id", table_name="pm_sync_links")
    op.drop_table("pm_sync_links")
    op.drop_index("ix_pm_sync_bindings_thread_id", table_name="pm_sync_bindings")
    op.drop_index("ix_pm_sync_bindings_organization_id", table_name="pm_sync_bindings")
    op.drop_index("ix_pm_sync_bindings_user_id", table_name="pm_sync_bindings")
    op.drop_table("pm_sync_bindings")
