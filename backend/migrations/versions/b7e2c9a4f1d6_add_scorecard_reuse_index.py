"""Add indexed scorecard reuse identity and lineage.

Revision ID: b7e2c9a4f1d6
Revises: a4c8e1f3b2d7
"""

from alembic import op
import sqlalchemy as sa


revision = "b7e2c9a4f1d6"
down_revision = "a4c8e1f3b2d7"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("scorecards") as batch:
        batch.add_column(sa.Column("decision_fingerprint", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column(
            "decision_state_reusable", sa.Boolean(), nullable=False,
            server_default=sa.false(),
        ))
        batch.add_column(sa.Column("reused_from_scorecard_id", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("reuse_root_scorecard_id", sa.String(length=255), nullable=True))

    connection = op.get_bind()
    scorecards = sa.table(
        "scorecards",
        sa.column("id", sa.String()),
        sa.column("data", sa.JSON()),
        sa.column("decision_fingerprint", sa.String()),
        sa.column("decision_state_reusable", sa.Boolean()),
        sa.column("reused_from_scorecard_id", sa.String()),
        sa.column("reuse_root_scorecard_id", sa.String()),
    )
    for row in connection.execute(sa.select(scorecards.c.id, scorecards.c.data)):
        payload = row.data if isinstance(row.data, dict) else {}
        metadata = payload.get("meta") if isinstance(payload.get("meta"), dict) else {}
        provenance = payload.get("reuse_provenance") if isinstance(payload.get("reuse_provenance"), dict) else {}
        direct = str(
            provenance.get("source_scorecard_id")
            or metadata.get("reused_source_scorecard_id")
            or payload.get("reused_source_scorecard_id")
            or ""
        ).strip() or None
        root = str(provenance.get("root_scorecard_id") or direct or "").strip() or None
        connection.execute(
            scorecards.update().where(scorecards.c.id == row.id).values(
                decision_fingerprint=str(payload.get("decision_fingerprint") or "").strip() or None,
                decision_state_reusable=bool(payload.get("decision_state_reusable") is True),
                reused_from_scorecard_id=direct,
                reuse_root_scorecard_id=root,
            )
        )

    op.create_index("ix_scorecards_decision_fingerprint", "scorecards", ["decision_fingerprint"])
    op.create_index("ix_scorecards_decision_state_reusable", "scorecards", ["decision_state_reusable"])
    op.create_index("ix_scorecards_reused_from_scorecard_id", "scorecards", ["reused_from_scorecard_id"])
    op.create_index("ix_scorecards_reuse_root_scorecard_id", "scorecards", ["reuse_root_scorecard_id"])
    op.create_index(
        "ix_scorecards_org_reuse_lookup", "scorecards",
        ["organization_id", "decision_fingerprint", "decision_state_reusable", "archived_at", "updated_at"],
    )
    op.create_index(
        "ix_scorecards_user_reuse_lookup", "scorecards",
        ["user_id", "decision_fingerprint", "decision_state_reusable", "archived_at", "updated_at"],
    )


def downgrade():
    op.drop_index("ix_scorecards_user_reuse_lookup", table_name="scorecards")
    op.drop_index("ix_scorecards_org_reuse_lookup", table_name="scorecards")
    op.drop_index("ix_scorecards_reuse_root_scorecard_id", table_name="scorecards")
    op.drop_index("ix_scorecards_reused_from_scorecard_id", table_name="scorecards")
    op.drop_index("ix_scorecards_decision_state_reusable", table_name="scorecards")
    op.drop_index("ix_scorecards_decision_fingerprint", table_name="scorecards")
    with op.batch_alter_table("scorecards") as batch:
        batch.drop_column("reuse_root_scorecard_id")
        batch.drop_column("reused_from_scorecard_id")
        batch.drop_column("decision_state_reusable")
        batch.drop_column("decision_fingerprint")
