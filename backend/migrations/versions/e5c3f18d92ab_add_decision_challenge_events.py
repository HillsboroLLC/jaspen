"""add decision_challenge_events table

The challenge ledger — link 3 of the evidence chain
(docs/DECISION_IMPACT_REPORT_SPEC.md §4). Records the analytical work Jaspen
did on a decision, so the report can distinguish "the record grew" from "the
record grew because the analysis pressed on it".

Revision ID: e5c3f18d92ab
Revises: d2b8e64af117
Create Date: 2026-09-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "e5c3f18d92ab"
down_revision = "d2b8e64af117"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "decision_challenge_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("type", sa.String(length=40), nullable=False),
        # Identity is a stable key, never a label, so events on the same
        # decision element connect across the lifecycle.
        sa.Column("target_kind", sa.String(length=24), nullable=True),
        sa.Column("target_id", sa.String(length=120), nullable=True),
        sa.Column("target_label", sa.String(length=255), nullable=True),
        sa.Column("trigger", sa.JSON(), nullable=False),
        sa.Column("origin", sa.String(length=40), nullable=False),
        sa.Column("actor", sa.String(length=24), nullable=False),
        sa.Column("user_visible", sa.Boolean(), nullable=False),
        sa.Column("derivation_id", sa.String(length=120), nullable=True),
        sa.Column("dedupe_key", sa.String(length=200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # Idempotence enforced by the database: a retry, refresh or repeated
        # scoring call cannot make Jaspen appear to have done more work.
        sa.UniqueConstraint(
            "user_id", "thread_id", "epoch", "dedupe_key",
            name="uq_challenge_event_dedupe",
        ),
    )
    op.create_index(
        "ix_challenge_events_thread",
        "decision_challenge_events", ["user_id", "thread_id", "epoch"], unique=False,
    )
    op.create_index(
        op.f("ix_decision_challenge_events_organization_id"),
        "decision_challenge_events", ["organization_id"], unique=False,
    )
    op.create_index(
        op.f("ix_decision_challenge_events_target_id"),
        "decision_challenge_events", ["target_id"], unique=False,
    )
    op.create_index(
        op.f("ix_decision_challenge_events_thread_id"),
        "decision_challenge_events", ["thread_id"], unique=False,
    )
    op.create_index(
        op.f("ix_decision_challenge_events_type"),
        "decision_challenge_events", ["type"], unique=False,
    )
    op.create_index(
        op.f("ix_decision_challenge_events_user_id"),
        "decision_challenge_events", ["user_id"], unique=False,
    )


def downgrade():
    for name in (
        op.f("ix_decision_challenge_events_user_id"),
        op.f("ix_decision_challenge_events_type"),
        op.f("ix_decision_challenge_events_thread_id"),
        op.f("ix_decision_challenge_events_target_id"),
        op.f("ix_decision_challenge_events_organization_id"),
        "ix_challenge_events_thread",
    ):
        op.drop_index(name, table_name="decision_challenge_events")
    op.drop_table("decision_challenge_events")
