"""add decision_baselines table

The sealed intake baseline for the Decision Impact Report
(docs/DECISION_IMPACT_REPORT_SPEC.md §3). Its own table rather than a column
on decision_records for two reasons: it must be able to exist before a
Decision Record does, and it must survive that record being re-derived.

Revision ID: c1a7f3d95b04
Revises: b7e2d91a4c03
Create Date: 2026-09-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "c1a7f3d95b04"
down_revision = "b7e2d91a4c03"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "decision_baselines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        # Link 1 of the evidence chain: what the user supplied, verbatim.
        sa.Column("submission_payload", sa.JSON(), nullable=False),
        # Link 2: what was measured from it.
        sa.Column("measures", sa.JSON(), nullable=False),
        sa.Column("sealed_at", sa.DateTime(), nullable=True),
        sa.Column("sealed_by", sa.String(length=32), nullable=True),
        # Component hashes, so a mismatch identifies which half diverged.
        sa.Column("submission_hash", sa.String(length=80), nullable=True),
        sa.Column("measures_hash", sa.String(length=80), nullable=True),
        sa.Column("content_hash", sa.String(length=80), nullable=True),
        sa.Column("readiness_spec_version", sa.String(length=32), nullable=True),
        sa.Column("methodology_version", sa.String(length=32), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # One baseline per thread per epoch. A restatement opens a new epoch
        # rather than amending a sealed row.
        sa.UniqueConstraint("user_id", "thread_id", "epoch", name="uq_baseline_thread_epoch"),
    )
    op.create_index(
        op.f("ix_decision_baselines_organization_id"),
        "decision_baselines", ["organization_id"], unique=False,
    )
    op.create_index(
        op.f("ix_decision_baselines_thread_id"),
        "decision_baselines", ["thread_id"], unique=False,
    )
    op.create_index(
        op.f("ix_decision_baselines_user_id"),
        "decision_baselines", ["user_id"], unique=False,
    )


def downgrade():
    op.drop_index(op.f("ix_decision_baselines_user_id"), table_name="decision_baselines")
    op.drop_index(op.f("ix_decision_baselines_thread_id"), table_name="decision_baselines")
    op.drop_index(op.f("ix_decision_baselines_organization_id"), table_name="decision_baselines")
    op.drop_table("decision_baselines")
