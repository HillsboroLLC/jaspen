"""Remove legacy demo users

Revision ID: c7d1d8a9f2be
Revises: b2f9a2d4c1ef
Create Date: 2026-03-08 09:55:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c7d1d8a9f2be'
down_revision = 'b2f9a2d4c1ef'
branch_labels = None
depends_on = None


def upgrade():
    conn = op.get_bind()

    users = sa.table(
        'users',
        sa.column('id', sa.String(length=36)),
        sa.column('email', sa.String(length=255)),
    )
    user_sessions = sa.table(
        'user_sessions',
        sa.column('user_id', sa.String(length=36)),
    )

    demo_emails = ['demo@jaspen.ai']
    demo_ids = [
        row[0]
        for row in conn.execute(
            sa.select(users.c.id).where(sa.func.lower(users.c.email).in_(demo_emails))
        ).fetchall()
    ]

    if not demo_ids:
        return

    conn.execute(user_sessions.delete().where(user_sessions.c.user_id.in_(demo_ids)))
    conn.execute(users.delete().where(users.c.id.in_(demo_ids)))


def downgrade():
    # One-way cleanup migration.
    pass
