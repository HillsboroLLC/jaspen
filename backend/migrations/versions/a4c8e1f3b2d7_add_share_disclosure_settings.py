"""Add per-link share disclosure settings and review confirmation.

Revision ID: a4c8e1f3b2d7
Revises: d8f1a2b3c4d5
"""

from alembic import op
import sqlalchemy as sa


revision = "a4c8e1f3b2d7"
down_revision = "d8f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("shared_artifacts") as batch:
        batch.add_column(sa.Column(
            "disclosure_settings",
            sa.JSON(),
            nullable=True,
            server_default=sa.text("'{}'"),
        ))
        batch.add_column(sa.Column("disclosure_reviewed_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE shared_artifacts SET disclosure_settings = '{}' WHERE disclosure_settings IS NULL")
    with op.batch_alter_table("shared_artifacts") as batch:
        batch.alter_column(
            "disclosure_settings",
            nullable=False,
            server_default=sa.text("'{}'"),
        )


def downgrade():
    with op.batch_alter_table("shared_artifacts") as batch:
        batch.drop_column("disclosure_reviewed_at")
        batch.drop_column("disclosure_settings")
