"""add option-scoped decision history

Revision ID: d8f1a2b3c4d5
Revises: c6e2f9a4b713
Create Date: 2026-10-14

The session-level decision_records row remains intact. Existing human decision
text is never moved or cleared. When its payload identifies a canonical option,
the decision is additionally copied into the new option-scoped history table.
Rows without option identity remain session-level exactly as before.
"""

import json
import uuid
from datetime import datetime

import sqlalchemy as sa
from alembic import op


revision = 'd8f1a2b3c4d5'
down_revision = 'c6e2f9a4b713'
branch_labels = None
depends_on = None


def _payload(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _payload_list(value):
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (TypeError, ValueError):
            return []
    return []


def _datetime(value):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).replace(tzinfo=None)
        except ValueError:
            return None
    return None


def upgrade():
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if 'decision_option_decisions' not in tables:
        op.create_table(
            'decision_option_decisions',
            sa.Column('id', sa.String(length=36), nullable=False),
            sa.Column('decision_record_id', sa.String(length=36), nullable=False),
            sa.Column('option_key', sa.String(length=160), nullable=False),
            sa.Column('option_name', sa.String(length=255), nullable=True),
            sa.Column('final_decision', sa.Text(), nullable=False),
            sa.Column('rationale', sa.Text(), nullable=True),
            sa.Column('source', sa.String(length=32), nullable=False, server_default='manual'),
            sa.Column('kit_verdict', sa.JSON(), nullable=True),
            sa.Column('override_info', sa.JSON(), nullable=True),
            sa.Column('decided_by_user_id', sa.String(length=36), nullable=True),
            sa.Column('decided_by_name', sa.String(length=255), nullable=True),
            sa.Column('supersedes_id', sa.String(length=36), nullable=True),
            sa.Column('superseded_at', sa.DateTime(), nullable=True),
            sa.Column('outcomes', sa.JSON(), nullable=False, server_default='[]'),
            sa.Column('lessons_learned', sa.JSON(), nullable=False, server_default='[]'),
            sa.Column('decided_at', sa.DateTime(), nullable=False),
            sa.Column('created_at', sa.DateTime(), nullable=False),
            sa.Column('updated_at', sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(['decision_record_id'], ['decision_records.id'], ondelete='CASCADE'),
            sa.ForeignKeyConstraint(['decided_by_user_id'], ['users.id'], ondelete='SET NULL'),
            sa.ForeignKeyConstraint(['supersedes_id'], ['decision_option_decisions.id'], ondelete='SET NULL'),
            sa.PrimaryKeyConstraint('id'),
        )
        op.create_index('ix_decision_option_decisions_record_id', 'decision_option_decisions', ['decision_record_id'])
        op.create_index('ix_decision_option_decisions_option_key', 'decision_option_decisions', ['option_key'])
        op.create_index('ix_decision_option_decisions_source', 'decision_option_decisions', ['source'])
        op.create_index('ix_decision_option_decisions_decided_by', 'decision_option_decisions', ['decided_by_user_id'])
        op.create_index('ix_decision_option_decisions_supersedes_id', 'decision_option_decisions', ['supersedes_id'])

    rows = bind.execute(sa.text(
        'SELECT id, user_id, final_decision, record, outcomes, lessons_learned, '
        'decided_at, created_at, updated_at '
        'FROM decision_records WHERE final_decision IS NOT NULL'
    )).mappings().all()
    option_table = sa.table(
        'decision_option_decisions',
        sa.column('id', sa.String()), sa.column('decision_record_id', sa.String()),
        sa.column('option_key', sa.String()), sa.column('option_name', sa.String()),
        sa.column('final_decision', sa.Text()), sa.column('rationale', sa.Text()),
        sa.column('source', sa.String()), sa.column('kit_verdict', sa.JSON()),
        sa.column('override_info', sa.JSON()), sa.column('decided_by_user_id', sa.String()),
        sa.column('decided_by_name', sa.String()), sa.column('supersedes_id', sa.String()),
        sa.column('superseded_at', sa.DateTime()), sa.column('outcomes', sa.JSON()),
        sa.column('lessons_learned', sa.JSON()), sa.column('decided_at', sa.DateTime()),
        sa.column('created_at', sa.DateTime()), sa.column('updated_at', sa.DateTime()),
    )
    for row in rows:
        payload = _payload(row['record'])
        verdict = payload.get('kit_verdict') if isinstance(payload.get('kit_verdict'), dict) else {}
        option_key = str(verdict.get('option_key') or payload.get('execution_option_key') or '').strip()
        if not option_key:
            continue
        card = next((
            item for item in (payload.get('scorecards') or [])
            if isinstance(item, dict) and str(item.get('option_key') or '').strip() == option_key
        ), {})
        human = payload.get('human_decision') if isinstance(payload.get('human_decision'), dict) else {}
        source = str(payload.get('decision_source') or verdict.get('source') or 'manual').strip()
        if source not in {'manual', 'build_execution_plan'}:
            source = 'manual'
        override_reason = str(verdict.get('override_reason') or '').strip() or None
        when = _datetime(row['decided_at'] or row['updated_at'] or row['created_at']) or datetime.utcnow()
        bind.execute(option_table.insert().values(
            id=str(uuid.uuid4()),
            decision_record_id=row['id'],
            option_key=option_key,
            option_name=str(card.get('name') or '').strip() or None,
            final_decision=row['final_decision'],
            rationale=override_reason,
            source=source,
            kit_verdict=verdict or None,
            override_info=(
                {'override_of': verdict.get('override_of'), 'override_reason': override_reason}
                if verdict.get('override_of') or override_reason else None
            ),
            decided_by_user_id=human.get('decided_by_user_id') or row['user_id'],
            decided_by_name=(payload.get('attribution') or {}).get('created_by_name'),
            supersedes_id=None,
            superseded_at=None,
            outcomes=list(_payload_list(row['outcomes'])),
            lessons_learned=list(_payload_list(row['lessons_learned'])),
            decided_at=when,
            created_at=when,
            updated_at=when,
        ))


def downgrade():
    bind = op.get_bind()
    if 'decision_option_decisions' not in set(sa.inspect(bind).get_table_names()):
        return
    for index_name in (
        'ix_decision_option_decisions_supersedes_id',
        'ix_decision_option_decisions_decided_by',
        'ix_decision_option_decisions_source',
        'ix_decision_option_decisions_option_key',
        'ix_decision_option_decisions_record_id',
    ):
        op.drop_index(index_name, table_name='decision_option_decisions')
    op.drop_table('decision_option_decisions')
