"""Deterministic, permission-aware decision intelligence from stored records."""

from collections import defaultdict
from datetime import datetime

from app.decision_records import can_read_record
from app.models import OrganizationMember, User
from app.models_decision_record import DecisionRecord, OptionDecision


OPEN_RECORD_STATUSES = frozenset({"in_analysis", "recorded"})
DECIDED_RECORD_STATUSES = frozenset({"decided", "outcome_recorded"})
RESOLVED_ASSUMPTION_STATUSES = frozenset({"resolved", "closed", "verified"})
PASSING_GATE_STATUSES = frozenset({"pass", "passed"})
COMPLETED_TASK_STATUSES = frozenset({"done", "complete", "completed"})


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else None


def _text(value, *keys):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in keys:
            text = str(value.get(key) or "").strip()
            if text:
                return text
    return ""


def _scorecards(record):
    payload = record.record if isinstance(record.record, dict) else {}
    cards = payload.get("scorecards")
    return cards if isinstance(cards, list) else []


def _unresolved_items(record):
    gates, assumptions, evidence = [], [], []
    for card in _scorecards(record):
        if not isinstance(card, dict):
            continue
        option = str(card.get("name") or "Option").strip()
        for gate in card.get("gates") if isinstance(card.get("gates"), list) else []:
            if not isinstance(gate, dict):
                continue
            status = str(gate.get("status") or "unknown").strip().lower()
            if status in PASSING_GATE_STATUSES:
                continue
            label = _text(gate, "label", "name", "key")
            if label:
                gates.append({"option": option, "label": label, "status": status})
        for assumption in card.get("assumptions") if isinstance(card.get("assumptions"), list) else []:
            status = str(assumption.get("status") or "open").strip().lower() if isinstance(assumption, dict) else "open"
            if status in RESOLVED_ASSUMPTION_STATUSES:
                continue
            label = _text(assumption, "assumption", "text", "label", "description")
            if label:
                assumptions.append({"option": option, "label": label, "status": status})
        profile = card.get("evidence_profile") if isinstance(card.get("evidence_profile"), dict) else {}
        for criterion in profile.get("criteria") if isinstance(profile.get("criteria"), list) else []:
            if not isinstance(criterion, dict):
                continue
            confidence = str(criterion.get("confidence") or "").strip().lower()
            evidenced = criterion.get("evidenced")
            if evidenced is not False and confidence != "assumed":
                continue
            label = _text(criterion, "label", "name", "criterion", "key")
            if label:
                evidence.append({"option": option, "label": label, "confidence": confidence or "missing"})
    return {"gates": gates, "assumptions": assumptions, "missing_evidence": evidence}


def _plan_progress(record):
    payload = record.record if isinstance(record.record, dict) else {}
    plan = payload.get("execution_plan")
    if not isinstance(plan, (dict, list)):
        return None
    tasks = []
    if isinstance(plan, list):
        tasks = [item for item in plan if isinstance(item, dict)]
    else:
        tasks.extend(item for item in (plan.get("tasks") or []) if isinstance(item, dict))
        for phase in plan.get("phases") if isinstance(plan.get("phases"), list) else []:
            if isinstance(phase, dict):
                tasks.extend(item for item in (phase.get("tasks") or []) if isinstance(item, dict))
    if not tasks:
        return {"tasks_total": 0, "tasks_completed": 0}
    completed = sum(
        1 for task in tasks
        if str(task.get("status") or "").strip().lower() in COMPLETED_TASK_STATUSES
    )
    return {"tasks_total": len(tasks), "tasks_completed": completed}


def _current_option_decisions(rows):
    superseded_ids = {str(row.supersedes_id) for row in rows if row.supersedes_id}
    current = defaultdict(list)
    for row in sorted(rows, key=lambda item: (item.decided_at or datetime.min, item.created_at or datetime.min), reverse=True):
        if str(row.id) not in superseded_ids:
            current[str(row.decision_record_id)].append(row)
    return current


def build_decision_overview(user, scope_context):
    """Build an uncapped overview. Resource visibility is always can_read_record."""
    organization = scope_context["organization"]
    membership = scope_context["membership"]
    records = (
        DecisionRecord.query
        .filter(DecisionRecord.organization_id == str(organization.id))
        .order_by(DecisionRecord.updated_at.desc(), DecisionRecord.id.asc())
        .all()
    )
    visible = [
        record for record in records
        if (scope_context["scope"] == "organization" or str(record.user_id or "") == str(user.id))
        and can_read_record(record, user, membership=membership)
    ]

    record_ids = [str(record.id) for record in visible]
    option_rows = (
        OptionDecision.query.filter(OptionDecision.decision_record_id.in_(record_ids)).all()
        if record_ids else []
    )
    options_by_record = _current_option_decisions(option_rows)
    all_options_by_record = defaultdict(list)
    for option in option_rows:
        all_options_by_record[str(option.decision_record_id)].append(option)

    user_ids = {str(record.user_id) for record in visible if record.user_id}
    users = User.query.filter(User.id.in_(user_ids)).all() if user_ids else []
    names = {str(item.id): str(item.name or item.email or item.id) for item in users}

    decisions, open_items, lessons, outcomes, plans = [], [], [], [], []
    monthly = defaultdict(lambda: {"records_created": 0, "decisions_made": 0})
    member_counts = defaultdict(lambda: {"records": 0, "decisions": 0, "open": 0})

    for record in visible:
        owner_id = str(record.user_id or "")
        owner_name = names.get(owner_id, "Former member" if not owner_id else "Unknown")
        member_counts[owner_id]["records"] += 1
        if record.created_at:
            monthly[record.created_at.strftime("%Y-%m")]["records_created"] += 1

        current_options = options_by_record.get(str(record.id), [])
        recorded_decisions = current_options if str(record.status or "") in DECIDED_RECORD_STATUSES else []
        for option in recorded_decisions:
            decisions.append({
                "id": str(option.id), "record_id": str(record.id), "thread_id": str(record.thread_id),
                "option_key": str(option.option_key),
                "title": record.title, "chosen_option": option.option_name or option.final_decision,
                "decision": option.final_decision, "decided_at": _iso(option.decided_at),
                "owner_user_id": owner_id or None, "owner_name": owner_name,
            })
            member_counts[owner_id]["decisions"] += 1
            if option.decided_at:
                monthly[option.decided_at.strftime("%Y-%m")]["decisions_made"] += 1
        if not recorded_decisions and record.final_decision and str(record.status or "") in DECIDED_RECORD_STATUSES:
            decisions.append({
                "id": f"legacy:{record.id}", "record_id": str(record.id), "thread_id": str(record.thread_id),
                "option_key": None,
                "title": record.title, "chosen_option": record.final_decision,
                "decision": record.final_decision, "decided_at": _iso(record.decided_at),
                "owner_user_id": owner_id or None, "owner_name": owner_name,
            })
            member_counts[owner_id]["decisions"] += 1
            if record.decided_at:
                monthly[record.decided_at.strftime("%Y-%m")]["decisions_made"] += 1

        unresolved = _unresolved_items(record)
        if str(record.status or "") in OPEN_RECORD_STATUSES or any(unresolved.values()):
            open_items.append({
                "record_id": str(record.id), "thread_id": str(record.thread_id),
                "title": record.title, "status": record.status, "unresolved": unresolved,
                "updated_at": _iso(record.updated_at), "owner_name": owner_name,
            })
            member_counts[owner_id]["open"] += 1

        for entry in record.outcomes if isinstance(record.outcomes, list) else []:
            text = _text(entry, "summary", "outcome", "text")
            if text:
                outcomes.append({"record_id": str(record.id), "thread_id": str(record.thread_id), "title": record.title, "text": text, "recorded_at": entry.get("recorded_at") if isinstance(entry, dict) else None})
        for entry in record.lessons_learned if isinstance(record.lessons_learned, list) else []:
            text = _text(entry, "lesson", "summary", "text")
            if text:
                lessons.append({"record_id": str(record.id), "thread_id": str(record.thread_id), "title": record.title, "text": text, "recorded_at": entry.get("recorded_at") if isinstance(entry, dict) else None})
        for option in all_options_by_record.get(str(record.id), []):
            for entry in option.outcomes if isinstance(option.outcomes, list) else []:
                text = _text(entry, "summary", "outcome", "text")
                if text:
                    outcomes.append({"record_id": str(record.id), "thread_id": str(record.thread_id), "title": record.title, "option": option.option_name, "text": text, "recorded_at": entry.get("recorded_at") if isinstance(entry, dict) else None})
            for entry in option.lessons_learned if isinstance(option.lessons_learned, list) else []:
                text = _text(entry, "lesson", "summary", "text")
                if text:
                    lessons.append({"record_id": str(record.id), "thread_id": str(record.thread_id), "title": record.title, "option": option.option_name, "text": text, "recorded_at": entry.get("recorded_at") if isinstance(entry, dict) else None})

        progress = _plan_progress(record)
        if progress and (progress["tasks_total"] == 0 or progress["tasks_completed"] < progress["tasks_total"]):
            plans.append({"record_id": str(record.id), "thread_id": str(record.thread_id), "title": record.title, **progress})

    decisions.sort(key=lambda item: item.get("decided_at") or "", reverse=True)
    lessons.sort(key=lambda item: item.get("recorded_at") or "", reverse=True)
    outcomes.sort(key=lambda item: item.get("recorded_at") or "", reverse=True)
    trend = [{"month": month, **monthly[month]} for month in sorted(monthly)]

    active_members = OrganizationMember.query.filter_by(organization_id=organization.id, status="active").all()
    member_ids = [str(item.user_id) for item in active_members if item.user_id]
    member_users = User.query.filter(User.id.in_(member_ids)).all() if member_ids else []
    member_names = {str(item.id): str(item.name or item.email or item.id) for item in member_users}
    activity_by_member = [
        {"user_id": member_id, "name": member_names.get(member_id, "Unknown"), **member_counts[member_id]}
        for member_id in member_ids if member_counts[member_id]["records"]
    ] if scope_context["scope"] == "organization" and scope_context["can_manage"] else []

    return {
        "organization": {"id": organization.id, "name": organization.name},
        "scope": scope_context["scope"],
        "requested_scope": scope_context["requested_scope"],
        "can_manage": scope_context["can_manage"],
        "calculation_label": "Calculated insights",
        "metrics": {
            "decision_records": len(visible), "decisions_made": len(decisions),
            "in_progress": sum(1 for record in visible if str(record.status or "") in OPEN_RECORD_STATUSES),
            "needs_attention": len(open_items), "lessons_recorded": len(lessons),
            "outcomes_recorded": len(outcomes), "plans_in_execution": len(plans),
        },
        "decisions": decisions, "open_items": open_items,
        "learning": {"outcomes": outcomes, "lessons": lessons},
        "progress": {"monthly": trend, "plans_in_execution": plans},
        "activity_by_member": activity_by_member,
        "limits": {"records_capped": False, "items_capped": False},
    }
