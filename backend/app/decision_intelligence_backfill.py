"""Idempotent Phase-0 decision-intelligence backfill."""

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm.attributes import flag_modified

from . import db
from .decision_records import (
    DISPOSITION_NOT_PURSUE,
    DISPOSITION_PURSUE,
    DISPOSITION_STILL_EVALUATING,
    _sync_option_decision_summary,
    _with_first_scored_times,
    execution_option_key,
    is_plan_decision_source,
)
from .models import UserSession
from .models_decision_record import DecisionRecord, OptionDecision


def _when(value, fallback):
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace('Z', '+00:00')).replace(tzinfo=None)
        except ValueError:
            pass
    return fallback or datetime.utcnow()


def _template_disposition(row):
    name = str(row.option_name or '').strip()
    templates = {
        f'Moving forward with {name}.': DISPOSITION_PURSUE,
        f'Moving forward with {name} — execution plan built.': DISPOSITION_PURSUE,
        f'Declined {name}.': DISPOSITION_NOT_PURSUE,
        f'Deferred {name}.': DISPOSITION_STILL_EVALUATING,
    }
    return templates.get(str(row.final_decision or ''))


def _mapped_disposition(row):
    verdict = row.kit_verdict if isinstance(row.kit_verdict, dict) else {}
    mapped = {
        'advance': DISPOSITION_PURSUE,
        'advance_with_conditions': DISPOSITION_PURSUE,
        'decline': DISPOSITION_NOT_PURSUE,
        'deferred': DISPOSITION_STILL_EVALUATING,
    }.get(verdict.get('verdict_key'))
    if mapped:
        return mapped
    if is_plan_decision_source(row.source):
        return DISPOSITION_PURSUE
    return _template_disposition(row)


def backfill_decision_intelligence(*, dry_run=False):
    counts = {
        'option_decisions_mapped': 0,
        'option_decisions_unmapped': 0,
        'legacy_plan_decisions_created': 0,
        'records_first_scored_updated': 0,
        'legacy_plans_marked': 0,
    }
    for row in OptionDecision.query.filter(OptionDecision.disposition.is_(None)).all():
        disposition = _mapped_disposition(row)
        if disposition is None:
            counts['option_decisions_unmapped'] += 1
            continue
        row.disposition = disposition
        metadata = dict(row.capture_metadata or {})
        if disposition == DISPOSITION_STILL_EVALUATING:
            metadata['deferred'] = True
        row.capture_metadata = metadata
        counts['option_decisions_mapped'] += 1

    records = DecisionRecord.query.order_by(DecisionRecord.created_at.asc()).all()
    for record in records:
        session = (
            UserSession.query.filter_by(session_id=str(record.thread_id))
            .order_by(UserSession.created_at.asc()).first()
        )
        old_payload = record.record if isinstance(record.record, dict) else {}
        new_payload = _with_first_scored_times(
            old_payload, existing_payload=old_payload, session_row=session,
            record_created_at=record.created_at,
        )
        if new_payload != old_payload:
            record.record = new_payload
            flag_modified(record, 'record')
            counts['records_first_scored_updated'] += 1
        if session is None:
            continue
        scenarios = dict(session.scenarios_json or {})
        by_card = scenarios.get('wbs_by_scorecard') if isinstance(scenarios.get('wbs_by_scorecard'), dict) else {}
        if not by_card and isinstance(scenarios.get('project_wbs'), dict):
            legacy = scenarios['project_wbs']
            legacy_id = str(legacy.get('scorecard_id') or '').strip()
            if legacy_id:
                by_card = {legacy_id: legacy}
        cards = [card for card in (new_payload.get('scorecards') or []) if isinstance(card, dict)]
        cards_by_id = {
            str(card.get('id') or card.get('analysis_id') or ''): card for card in cards
        }
        session_changed = False
        for scorecard_id, plan in by_card.items():
            if not isinstance(plan, dict):
                continue
            if 'decision_basis' not in plan:
                plan['decision_basis'] = None
                plan['decision_basis_reason'] = 'created_before_snapshot'
                counts['legacy_plans_marked'] += 1
                session_changed = True
            card = cards_by_id.get(str(scorecard_id))
            if not card:
                continue
            option_key = execution_option_key(card)
            exists = OptionDecision.query.filter_by(
                decision_record_id=str(record.id), option_key=option_key,
            ).first()
            if exists:
                continue
            created_at = _when(plan.get('created_at'), record.created_at)
            row = OptionDecision(
                decision_record_id=str(record.id),
                option_key=option_key,
                option_name=card.get('name'),
                final_decision=f"Moving forward with {card.get('name') or 'this option'} — legacy execution plan.",
                source='legacy_plan',
                disposition=DISPOSITION_PURSUE,
                capture_metadata={},
                decided_by_user_id=str(session.created_by_user_id or record.user_id or '') or None,
                decided_at=created_at,
                created_at=created_at,
                updated_at=created_at,
            )
            db.session.add(row)
            counts['legacy_plan_decisions_created'] += 1
        if session_changed:
            scenarios['wbs_by_scorecard'] = by_card
            if isinstance(scenarios.get('project_wbs'), dict):
                active = str(scenarios.get('active_execution_scorecard_id') or scenarios['project_wbs'].get('scorecard_id') or '')
                if active in by_card:
                    scenarios['project_wbs'] = by_card[active]
            session.scenarios_json = scenarios
            flag_modified(session, 'scenarios_json')
        db.session.flush()
        _sync_option_decision_summary(record)

    db.session.flush()
    counts['report'] = _current_report()
    if dry_run:
        db.session.rollback()
    else:
        db.session.commit()
    return counts


def _current_report():
    dispositions_by_source = {}
    for source, disposition, total in (
        db.session.query(OptionDecision.source, OptionDecision.disposition, func.count(OptionDecision.id))
        .group_by(OptionDecision.source, OptionDecision.disposition)
        .order_by(OptionDecision.source, OptionDecision.disposition)
        .all()
    ):
        source_counts = dispositions_by_source.setdefault(source, {})
        source_counts[disposition or 'unmapped'] = int(total)

    records_with_first_scored_at = 0
    for record in DecisionRecord.query.all():
        payload = record.record if isinstance(record.record, dict) else {}
        cards = payload.get('scorecards') if isinstance(payload.get('scorecards'), list) else []
        if any(isinstance(card, dict) and card.get('first_scored_at') for card in cards):
            records_with_first_scored_at += 1

    plans_marked = 0
    for session in UserSession.query.all():
        scenarios = session.scenarios_json if isinstance(session.scenarios_json, dict) else {}
        plans = scenarios.get('wbs_by_scorecard') if isinstance(scenarios.get('wbs_by_scorecard'), dict) else {}
        if not plans and isinstance(scenarios.get('project_wbs'), dict):
            plans = {'legacy': scenarios['project_wbs']}
        plans_marked += sum(
            1 for plan in plans.values()
            if isinstance(plan, dict) and plan.get('decision_basis_reason') == 'created_before_snapshot'
        )
    return {
        'dispositions_by_source': dispositions_by_source,
        'records_with_first_scored_at': records_with_first_scored_at,
        'plans_marked_created_before_snapshot': plans_marked,
    }
