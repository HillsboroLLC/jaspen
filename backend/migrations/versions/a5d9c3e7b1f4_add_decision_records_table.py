"""add decision_records table

Revision ID: a5d9c3e7b1f4
Revises: d4e5f6a7b8c9
Create Date: 2026-07-10 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a5d9c3e7b1f4"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "decision_records",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("thread_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("decision_statement", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("decision_type", sa.String(length=64), nullable=True),
        sa.Column("altitude", sa.String(length=32), nullable=True),
        sa.Column("library_consent", sa.String(length=16), nullable=False),
        sa.Column("library_consented_at", sa.DateTime(), nullable=True),
        sa.Column("internal_corpus_eligible", sa.Boolean(), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("record", sa.JSON(), nullable=False),
        sa.Column("final_decision", sa.Text(), nullable=True),
        sa.Column("outcomes", sa.JSON(), nullable=False),
        sa.Column("lessons_learned", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("outcome_recorded_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_decision_records_decision_type"), "decision_records", ["decision_type"], unique=False)
    op.create_index(op.f("ix_decision_records_organization_id"), "decision_records", ["organization_id"], unique=False)
    op.create_index(op.f("ix_decision_records_status"), "decision_records", ["status"], unique=False)
    op.create_index(op.f("ix_decision_records_thread_id"), "decision_records", ["thread_id"], unique=False)
    op.create_index(op.f("ix_decision_records_user_id"), "decision_records", ["user_id"], unique=False)


def downgrade():
    op.drop_index(op.f("ix_decision_records_user_id"), table_name="decision_records")
    op.drop_index(op.f("ix_decision_records_thread_id"), table_name="decision_records")
    op.drop_index(op.f("ix_decision_records_status"), table_name="decision_records")
    op.drop_index(op.f("ix_decision_records_organization_id"), table_name="decision_records")
    op.drop_index(op.f("ix_decision_records_decision_type"), table_name="decision_records")
    op.drop_table("decision_records")
