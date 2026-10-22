"""Organization access gate: share-link ownership and report-mode events.

Two new tables; no existing table is altered and no existing row is changed.

* shared_artifact_ownership -- which organization owns each share link,
  decided from the underlying report (the owner's UserSession row for the
  link's thread), not from the link's creator. Existing links are backfilled
  here; links whose report is missing or matches several owners are recorded
  as ``ambiguous`` for review.
* org_access_shadow_events -- accesses the membership rule refused, or would
  refuse while ORG_ACCESS_ENFORCEMENT=report.

Revision ID: d4e6f8a0b2c3
Revises: c3d5e7f9a1b2
"""

from datetime import datetime

from alembic import op
import sqlalchemy as sa


revision = "d4e6f8a0b2c3"
down_revision = "c3d5e7f9a1b2"
branch_labels = None
depends_on = None


def classify(org_ids):
    """(state, organization_id) for the organization ids of a link's report rows.

    ``None`` entries are rows with no organization. Mirrors
    app.share_ownership.classify; kept inline because migrations must not
    import application code.
    """
    if not org_ids:
        return "ambiguous", None
    distinct = set(org_ids)
    if distinct == {None}:
        return "personal", None
    if len(distinct) == 1:
        return "organization", next(iter(distinct))
    return "ambiguous", None


def upgrade():
    op.create_table(
        "shared_artifact_ownership",
        sa.Column(
            "shared_artifact_id",
            sa.String(length=36),
            sa.ForeignKey("shared_artifacts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False, server_default="created"),
        sa.Column("resolved_at", sa.DateTime(), nullable=False),
        sa.Column("resolved_by_user_id", sa.String(length=36), nullable=True),
        sa.Column("note", sa.String(length=255), nullable=True),
    )
    op.create_index(
        "ix_shared_artifact_ownership_organization_id",
        "shared_artifact_ownership",
        ["organization_id"],
    )

    op.create_table(
        "org_access_shadow_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("mode", sa.String(length=16), nullable=False),
        sa.Column("path", sa.String(length=120), nullable=False),
        sa.Column("resource_type", sa.String(length=64), nullable=False),
        sa.Column("resource_id", sa.String(length=255), nullable=True),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("reason", sa.String(length=64), nullable=False),
    )
    op.create_index("ix_org_access_shadow_events_created_at", "org_access_shadow_events", ["created_at"])
    op.create_index("ix_org_access_shadow_events_path", "org_access_shadow_events", ["path"])
    op.create_index("ix_org_access_shadow_events_organization_id", "org_access_shadow_events", ["organization_id"])
    op.create_index("ix_org_access_shadow_events_user_id", "org_access_shadow_events", ["user_id"])

    _backfill_ownership()


def _backfill_ownership():
    bind = op.get_bind()
    links = bind.execute(sa.text(
        "SELECT id, owner_user_id, thread_id FROM shared_artifacts"
    )).fetchall()
    if not links:
        return
    ownership = sa.table(
        "shared_artifact_ownership",
        sa.column("shared_artifact_id", sa.String),
        sa.column("state", sa.String),
        sa.column("organization_id", sa.String),
        sa.column("source", sa.String),
        sa.column("resolved_at", sa.DateTime),
    )
    now = datetime.utcnow()
    rows = []
    for link_id, owner_user_id, thread_id in links:
        org_ids = [
            org_id for (org_id,) in bind.execute(
                sa.text(
                    "SELECT organization_id FROM user_sessions "
                    "WHERE session_id = :sid AND (user_id = :uid OR created_by_user_id = :uid)"
                ),
                {"sid": thread_id, "uid": owner_user_id},
            ).fetchall()
        ]
        state, org_id = classify(org_ids)
        rows.append({
            "shared_artifact_id": link_id,
            "state": state,
            "organization_id": org_id,
            "source": "backfill",
            "resolved_at": now,
        })
    op.bulk_insert(ownership, rows)


def downgrade():
    op.drop_index("ix_org_access_shadow_events_user_id", table_name="org_access_shadow_events")
    op.drop_index("ix_org_access_shadow_events_organization_id", table_name="org_access_shadow_events")
    op.drop_index("ix_org_access_shadow_events_path", table_name="org_access_shadow_events")
    op.drop_index("ix_org_access_shadow_events_created_at", table_name="org_access_shadow_events")
    op.drop_table("org_access_shadow_events")
    op.drop_index("ix_shared_artifact_ownership_organization_id", table_name="shared_artifact_ownership")
    op.drop_table("shared_artifact_ownership")
