"""add capture provenance to decision_baselines

Distinguishes a baseline sealed BEFORE analysis began (contemporaneous, the
only kind that can support a Before/After comparison) from one assembled after
(reconstructed). See docs/DECISION_IMPACT_REPORT_SPEC.md §3.8.

`sealed_by` already recorded who sealed. It could not record whether the seal
was in time, and those are different questions.

Revision ID: d2b8e64af117
Revises: c1a7f3d95b04
Create Date: 2026-09-03 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "d2b8e64af117"
down_revision = "c1a7f3d95b04"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "decision_baselines",
        sa.Column(
            "capture",
            sa.String(length=32),
            nullable=False,
            server_default="contemporaneous",
        ),
    )
    op.add_column(
        "decision_baselines",
        sa.Column("capture_reason", sa.String(length=64), nullable=True),
    )

    # Any baseline already sealed when this column arrived was sealed by code
    # that had no concept of capture timing, so nothing establishes that it
    # preceded the analysis. Mark those reconstructed rather than inheriting
    # the column default — a wrong `contemporaneous` is exactly the claim this
    # migration exists to prevent, and the conservative reading costs nothing.
    op.execute(
        """
        UPDATE decision_baselines
           SET capture = 'reconstructed',
               capture_reason = 'no_baseline_before_analysis'
         WHERE sealed_at IS NOT NULL
        """
    )


def downgrade():
    op.drop_column("decision_baselines", "capture_reason")
    op.drop_column("decision_baselines", "capture")
