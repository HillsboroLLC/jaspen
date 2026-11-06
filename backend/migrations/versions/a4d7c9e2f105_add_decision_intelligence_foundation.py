"""Add the decision-intelligence data foundation.

Revision ID: a4d7c9e2f105
Revises: f1a2b3c4d5e6
"""

from alembic import op
import sqlalchemy as sa
import json
import uuid
from datetime import datetime


revision = "a4d7c9e2f105"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def _json(value, fallback):
    if isinstance(value, type(fallback)):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, type(fallback)) else fallback
        except (TypeError, ValueError):
            return fallback
    return fallback


def _when(value, fallback=None):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).replace(tzinfo=None)
        except ValueError:
            pass
    return fallback or datetime.utcnow()


def upgrade():
    with op.batch_alter_table("decision_option_decisions") as batch:
        batch.add_column(sa.Column("disposition", sa.String(32), nullable=True))
        batch.add_column(sa.Column("user_quote", sa.Text(), nullable=True))
        batch.add_column(sa.Column("basis_snapshot", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("capture_metadata", sa.JSON(), nullable=False, server_default=sa.text("'{}'")))
        batch.create_index("ix_decision_option_decisions_disposition", ["disposition"])

    bind = op.get_bind()
    rows = bind.execute(sa.text(
        "SELECT id, option_name, final_decision, source, kit_verdict, capture_metadata "
        "FROM decision_option_decisions WHERE disposition IS NULL"
    )).mappings().all()
    for row in rows:
        verdict = _json(row['kit_verdict'], {}).get('verdict_key')
        disposition = {
            'advance': 'pursue', 'advance_with_conditions': 'pursue',
            'decline': 'not_pursue', 'deferred': 'still_evaluating',
        }.get(verdict)
        if disposition is None and row['source'] in {
            'build_execution_plan', 'plan_created', 'legacy_plan',
        }:
            disposition = 'pursue'
        if disposition is None:
            name = str(row['option_name'] or '').strip()
            disposition = {
                f'Moving forward with {name}.': 'pursue',
                f'Moving forward with {name} — execution plan built.': 'pursue',
                f'Declined {name}.': 'not_pursue',
                f'Deferred {name}.': 'still_evaluating',
            }.get(str(row['final_decision'] or ''))
        if disposition:
            metadata = _json(row['capture_metadata'], {})
            if disposition == 'still_evaluating':
                metadata['deferred'] = True
            bind.execute(sa.text(
                "UPDATE decision_option_decisions SET disposition=:disposition, source=:source, "
                "capture_metadata=:metadata WHERE id=:id"
            ), {
                'id': row['id'], 'disposition': disposition,
                'source': 'plan_created' if row['source'] == 'build_execution_plan' else row['source'],
                'metadata': json.dumps(metadata),
            })

    op.create_table(
        "decision_signals",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=True),
        sa.Column("attribution_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("decision_record_id", sa.String(36), sa.ForeignKey("decision_records.id", ondelete="CASCADE"), nullable=False),
        sa.Column("option_key", sa.String(160), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("user_quote", sa.Text(), nullable=True),
        sa.Column("structured", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(32), nullable=False),
        sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("supersedes_id", sa.String(36), sa.ForeignKey("decision_signals.id", ondelete="SET NULL"), nullable=True),
        sa.Column("retracted_at", sa.DateTime(), nullable=True),
        sa.Column("retracted_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    for column in (
        "organization_id", "attribution_user_id", "thread_id", "decision_record_id",
        "option_key", "kind", "source", "actor_user_id", "occurred_at",
        "supersedes_id", "retracted_at",
    ):
        op.create_index(f"ix_decision_signals_{column}", "decision_signals", [column])

    tables = set(sa.inspect(bind).get_table_names())
    if {'decision_records', 'user_sessions', 'scorecards'}.issubset(tables):
        records = bind.execute(sa.text(
            "SELECT id, user_id, thread_id, record, created_at FROM decision_records"
        )).mappings().all()
        score_rows = bind.execute(sa.text(
            "SELECT id, thread_id, data, created_at FROM scorecards ORDER BY created_at, id"
        )).mappings().all()
        by_thread = {}
        for score in score_rows:
            data = _json(score['data'], {})
            key = str(data.get('option_key') or f"scorecard:{score['id']}")
            by_thread.setdefault(str(score['thread_id']), {}).setdefault(key, score['created_at'])
        for record_row in records:
            payload = _json(record_row['record'], {})
            changed = False
            for card in payload.get('scorecards') if isinstance(payload.get('scorecards'), list) else []:
                if not isinstance(card, dict) or card.get('first_scored_at'):
                    continue
                key = str(card.get('option_key') or f"scorecard:{card.get('id') or ''}")
                first = by_thread.get(str(record_row['thread_id']), {}).get(key)
                if first:
                    card['first_scored_at'] = _when(first).isoformat()
                    card['first_scored_source'] = 'scorecard.created_at'
                else:
                    generated_field = 'generated_at' if card.get('generated_at') else 'createdAt'
                    fallback = card.get(generated_field)
                    card['first_scored_at'] = _when(fallback, record_row['created_at']).isoformat()
                    card['first_scored_source'] = (
                        f'scorecard.{generated_field}' if fallback else 'decision_record.created_at'
                    )
                changed = True
            if changed:
                bind.execute(sa.text("UPDATE decision_records SET record=:record WHERE id=:id"), {
                    'id': record_row['id'], 'record': json.dumps(payload),
                })

            session = bind.execute(sa.text(
                "SELECT id, created_by_user_id, payload, scenarios_json FROM user_sessions "
                "WHERE session_id=:thread_id ORDER BY created_at LIMIT 1"
            ), {'thread_id': record_row['thread_id']}).mappings().first()
            if not session:
                continue
            session_payload = _json(session['payload'], {})
            registry = session_payload.get('option_registry') if isinstance(session_payload.get('option_registry'), dict) else {}
            registry_changed = False
            record_cards_by_key = {
                str(card.get('option_key') or f"scorecard:{card.get('id') or ''}"): card
                for card in (payload.get('scorecards') or []) if isinstance(card, dict)
            }
            for key, item in registry.items():
                if not isinstance(item, dict) or item.get('first_scored_at'):
                    continue
                first = by_thread.get(str(record_row['thread_id']), {}).get(str(key))
                if first:
                    item['first_scored_at'] = _when(first).isoformat()
                    item['first_scored_source'] = 'scorecard.created_at'
                    registry_changed = True
                elif record_cards_by_key.get(str(key), {}).get('first_scored_at'):
                    card = record_cards_by_key[str(key)]
                    item['first_scored_at'] = card['first_scored_at']
                    item['first_scored_source'] = card.get('first_scored_source')
                    registry_changed = True
            if registry_changed:
                session_payload['option_registry'] = registry
                bind.execute(sa.text(
                    "UPDATE user_sessions SET payload=:payload WHERE id=:id"
                ), {'id': session['id'], 'payload': json.dumps(session_payload)})
            scenarios = _json(session['scenarios_json'], {})
            plans = scenarios.get('wbs_by_scorecard') if isinstance(scenarios.get('wbs_by_scorecard'), dict) else {}
            if not plans and isinstance(scenarios.get('project_wbs'), dict):
                legacy = scenarios['project_wbs']
                legacy_id = str(legacy.get('scorecard_id') or '').strip()
                if legacy_id:
                    plans = {legacy_id: legacy}
            cards_by_id = {
                str(card.get('id') or card.get('analysis_id') or ''): card
                for card in (payload.get('scorecards') or []) if isinstance(card, dict)
            }
            scenario_changed = False
            for scorecard_id, plan in plans.items():
                if not isinstance(plan, dict):
                    continue
                if 'decision_basis' not in plan:
                    plan['decision_basis'] = None
                    plan['decision_basis_reason'] = 'created_before_snapshot'
                    scenario_changed = True
                card = cards_by_id.get(str(scorecard_id))
                if not card:
                    continue
                option_key = str(card.get('option_key') or f'scorecard:{scorecard_id}')
                exists = bind.execute(sa.text(
                    "SELECT id FROM decision_option_decisions "
                    "WHERE decision_record_id=:record_id AND option_key=:option_key LIMIT 1"
                ), {'record_id': record_row['id'], 'option_key': option_key}).first()
                if exists:
                    continue
                when = _when(plan.get('created_at'), record_row['created_at'])
                bind.execute(sa.text(
                    "INSERT INTO decision_option_decisions "
                    "(id, decision_record_id, option_key, option_name, final_decision, source, "
                    "disposition, capture_metadata, decided_by_user_id, outcomes, lessons_learned, "
                    "decided_at, created_at, updated_at) VALUES "
                    "(:id, :record_id, :option_key, :option_name, :final_decision, 'legacy_plan', "
                    "'pursue', :metadata, :actor, :outcomes, :lessons, :decided_at, :created_at, :updated_at)"
                ), {
                    'id': str(uuid.uuid4()), 'record_id': record_row['id'],
                    'option_key': option_key, 'option_name': card.get('name'),
                    'final_decision': f"Moving forward with {card.get('name') or 'this option'} — legacy execution plan.",
                    'metadata': json.dumps({}),
                    'actor': session['created_by_user_id'] or record_row['user_id'],
                    'outcomes': json.dumps([]), 'lessons': json.dumps([]),
                    'decided_at': when, 'created_at': when, 'updated_at': when,
                })
            if scenario_changed:
                scenarios['wbs_by_scorecard'] = plans
                if isinstance(scenarios.get('project_wbs'), dict):
                    active = str(
                        scenarios.get('active_execution_scorecard_id')
                        or scenarios['project_wbs'].get('scorecard_id') or ''
                    )
                    if active in plans:
                        scenarios['project_wbs'] = plans[active]
                bind.execute(sa.text(
                    "UPDATE user_sessions SET scenarios_json=:scenarios WHERE id=:id"
                ), {'id': session['id'], 'scenarios': json.dumps(scenarios)})


def downgrade():
    op.drop_table("decision_signals")
    with op.batch_alter_table("decision_option_decisions") as batch:
        batch.drop_index("ix_decision_option_decisions_disposition")
        batch.drop_column("capture_metadata")
        batch.drop_column("basis_snapshot")
        batch.drop_column("user_quote")
        batch.drop_column("disposition")
