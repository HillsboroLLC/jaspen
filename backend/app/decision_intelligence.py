"""Option-level Insights v3, calculated only from stored decision records."""

from collections import defaultdict
from datetime import datetime, timedelta, timezone

from app.decision_records import can_read_record, current_decision_signals, option_dispositions
from app.models import OrganizationMember, Scorecard, User, UserSession
from app.models_challenge_event import ChallengeEvent
from app.models_decision_record import DecisionRecord, DecisionSignal, OptionDecision
from app.decision_kits import get_decision_kit
from app.decision_kits.rfp_bid import KIT as RFP_KIT


DONE = frozenset({"done", "complete", "completed"})
PASS = frozenset({"pass", "passed"})
FAIL = frozenset({"fail", "failed"})
# Outcome statuses that mean results were measured (too_early means not yet).
MEASURED = frozenset({"achieved", "partially_achieved", "not_achieved", "abandoned"})


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else value if isinstance(value, str) else None


def _dt(value):
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value or "").replace("Z", "+00:00")).replace(tzinfo=None)
    except (TypeError, ValueError):
        return None


def _metric(value=None, *, numerator=None, denominator=None, coverage=None, unavailable_reason=None, **extra):
    return {
        "value": value,
        "numerator": numerator if numerator is not None else value,
        "denominator": denominator,
        "coverage": coverage if coverage is not None else denominator,
        "unavailable_reason": unavailable_reason,
        **extra,
    }


def _cards(record):
    payload = record.record if isinstance(record.record, dict) else {}
    return [card for card in (payload.get("scorecards") or []) if isinstance(card, dict)]


def _card_key(card):
    key = str(card.get("option_key") or "").strip()
    if key:
        return key
    card_id = str(card.get("id") or card.get("analysis_id") or "").strip()
    return f"scorecard:{card_id}" if card_id else ""


def _plans(session):
    scenarios = session.scenarios_json if session and isinstance(session.scenarios_json, dict) else {}
    plans = scenarios.get("wbs_by_scorecard") if isinstance(scenarios.get("wbs_by_scorecard"), dict) else {}
    if not plans and isinstance(scenarios.get("project_wbs"), dict):
        plan = scenarios["project_wbs"]
        plan_id = str(plan.get("scorecard_id") or "")
        plans = {plan_id: plan} if plan_id else {}
    return plans


def _tasks(plan):
    if not isinstance(plan, dict):
        return []
    found = [task for task in (plan.get("tasks") or []) if isinstance(task, dict)]
    for phase in plan.get("phases") or []:
        if isinstance(phase, dict):
            found.extend(task for task in (phase.get("tasks") or []) if isinstance(task, dict))
    return found


def _evidence_pct(card):
    profile = card.get("evidence_profile") if isinstance(card.get("evidence_profile"), dict) else {}
    value = profile.get("evidence_backed_pct")
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _basis(card, plans):
    ids = {str(card.get("id") or ""), str(card.get("analysis_id") or "")}
    matches = [(key, plan) for key, plan in plans.items() if str(key) in ids and isinstance(plan, dict)]
    matches.sort(key=lambda item: str(item[1].get("created_at") or ""))
    if not matches:
        return None, None
    plan = matches[0][1]
    basis = plan.get("decision_basis") if isinstance(plan.get("decision_basis"), dict) else None
    return plan, basis


def _gap_key(item):
    return str(item.get("key") or item.get("criterion_key") or item.get("id") or "").strip()


def _option_gaps(card, basis, tasks, resolved_events=None):
    basis = basis if isinstance(basis, dict) else {}
    gaps = []
    for item in basis.get("unevidenced_criteria") or []:
        if isinstance(item, dict):
            gaps.append({"kind": "criterion", "key": _gap_key(item), "label": item.get("label") or _gap_key(item), "group": item.get("group"), "resolution": item.get("resolution")})
    for gate in basis.get("gates") or card.get("gates") or []:
        if isinstance(gate, dict) and str(gate.get("status") or "unknown").lower() not in PASS:
            gaps.append({"kind": "gate", "key": str(gate.get("key") or ""), "label": gate.get("label") or gate.get("key"), "status": str(gate.get("status") or "unknown").lower()})
    current_criteria = {
        str(item.get("key") or item.get("criterion_key") or ""): item
        for item in ((card.get("evidence_profile") or {}).get("criteria") or [])
        if isinstance(item, dict)
    }
    current_gates = {
        str(item.get("key") or ""): item
        for item in (card.get("gates") or []) if isinstance(item, dict)
    }
    for gap in gaps:
        refs = []
        for task in tasks:
            lineage = task.get("lineage") if isinstance(task.get("lineage"), dict) else {}
            ref = str(lineage.get("ref") or lineage.get("key") or "")
            if ref and ref == gap["key"]:
                refs.append(task)
        gap["task_created"] = bool(refs)
        gap["task_completed"] = any(str(task.get("status") or "").lower() in DONE for task in refs)
        if gap["kind"] == "criterion":
            current = current_criteria.get(gap["key"], {})
            event_at = (resolved_events or {}).get(gap["key"])
            gap["resolved"] = bool(current.get("evidenced") is True or event_at)
            gap["resolved_at"] = _iso(event_at) if event_at else None
        else:
            current = current_gates.get(gap["key"], {})
            gap["resolved"] = str(current.get("status") or "").lower() in PASS
    return gaps


def _deadline(card):
    attrs = card.get("attributes")
    if isinstance(attrs, dict):
        value = attrs.get("submission_due")
        return value.get("value") if isinstance(value, dict) else value
    if isinstance(attrs, list):
        for item in attrs:
            if isinstance(item, dict) and item.get("key") == "submission_due":
                return item.get("value")
    return None


def _stated_deadline(option, today):
    """The nearest upcoming deadline: a stored kit fact or a deadline the customer stated."""
    dates = []
    fact = _dt(_deadline(option["card"]))
    if fact:
        dates.append(fact)
    for signal in option["signals"]:
        if signal.kind == "deadline":
            value = _dt((signal.structured or {}).get("date") if isinstance(signal.structured, dict) else None)
            if value:
                dates.append(value)
    upcoming = sorted(value for value in dates if value.date() >= today.date())
    return upcoming[0] if upcoming else None


def _attention(option, today):
    """Explainable exceptions only. Each trigger is facts: the UI composes its label."""
    triggers = []
    gates = [gate for gate in (option["card"].get("gates") or []) if isinstance(gate, dict)]
    due = _stated_deadline(option, today)
    deadline_window = RFP_KIT["attention_deadline_window_days"] if str(option["decision_kind_key"]).startswith("rfp") else None
    if due and deadline_window and option["state"] in {"open", "pursued"} and 0 <= (due.date() - today.date()).days <= deadline_window:
        open_gates = [gate for gate in gates if str(gate.get("status") or "unknown").lower() not in PASS]
        if open_gates:
            triggers.append({"kind": "decision_milestone_at_risk", "evidence": {"deadline": due.date().isoformat(), "window_days": deadline_window, "required_checks": [{"key": g.get("key"), "label": g.get("label") or g.get("key"), "status": g.get("status") or "unknown"} for g in open_gates]}, "next_step_ref": {"type": "gate", "id": open_gates[0].get("key")}, "available": True})
    failed = [gate for gate in gates if str(gate.get("status") or "").lower() in FAIL]
    addressed = {gap["key"] for gap in option["gaps"] if gap["task_created"]}
    for gate in failed:
        if option["state"] == "pursued" and str(gate.get("key") or "") not in addressed:
            triggers.append({"kind": "failed_required_check_without_task", "evidence": {"gate_key": gate.get("key"), "gate_label": gate.get("label") or gate.get("key"), "status": "failed"}, "next_step_ref": {"type": "gate", "id": gate.get("key")}, "available": True})
    overdue = {}
    for task in option["tasks"]:
        commitment = task.get("commitment") if isinstance(task.get("commitment"), dict) else None
        due_at = _dt((commitment or {}).get("rescheduled_to") or (commitment or {}).get("due_date"))
        if commitment and due_at and due_at.date() < today.date() and str(task.get("status") or "").lower() not in DONE:
            overdue[str(task.get("id"))] = task
            triggers.append({"kind": "committed_task_overdue", "evidence": {"task_id": task.get("id"), "task_name": task.get("name") or task.get("title"), "committed_due_date": (commitment or {}).get("due_date"), "current_due_date": (commitment or {}).get("rescheduled_to") or (commitment or {}).get("due_date")}, "next_step_ref": {"type": "task", "id": task.get("id")}, "available": True})
    for task in option["tasks"]:
        deps = task.get("depends_on") or []
        if any(str(dep) in overdue for dep in deps) and str(task.get("status") or "").lower() not in DONE:
            triggers.append({"kind": "blocked_by_overdue_commitment", "evidence": {"task_id": task.get("id"), "task_name": task.get("name") or task.get("title"), "predecessor_ids": [dep for dep in deps if str(dep) in overdue]}, "next_step_ref": {"type": "task", "id": task.get("id")}, "available": True})
    for signal in option["signals"]:
        structured = signal.structured if isinstance(signal.structured, dict) else {}
        review = _dt(structured.get("review_by"))
        if signal.kind == "success_measure" and review and review.date() < today.date() and not option["outcomes"]:
            triggers.append({"kind": "outcome_review_due", "evidence": {"signal_id": signal.id, "review_by": review.date().isoformat(), "measure": signal.content}, "next_step_ref": {"type": "signal", "id": signal.id}, "available": True})
    for condition in option["conditions"]:
        due_by = _dt(condition.get("due_by"))
        if option["state"] == "pursued" and condition["status"] == "open" and due_by and due_by.date() < today.date():
            triggers.append({"kind": "condition_past_due", "evidence": {"signal_id": condition["signal_id"], "condition": condition["content"], "due_by": due_by.date().isoformat()}, "next_step_ref": {"type": "signal", "id": condition["signal_id"]}, "available": True})
    return triggers


def _conditions(signals):
    """Current conditions (latest status of each) for one option."""
    rows = []
    for signal in current_decision_signals(signals):
        if signal.kind != "condition":
            continue
        structured = signal.structured if isinstance(signal.structured, dict) else {}
        rows.append({
            "signal_id": str(signal.id),
            "content": signal.content,
            "status": str(structured.get("status") or "open"),
            "due_by": structured.get("due_by"),
            "since": _iso(signal.occurred_at),
        })
    return rows


def build_insights_v3(user, scope_context, filters=None):
    """Build the complete v3 dashboard from one bounded set of database queries."""
    filters = filters or {}
    org = scope_context["organization"]
    membership = scope_context["membership"]
    records = DecisionRecord.query.filter_by(organization_id=str(org.id)).order_by(DecisionRecord.updated_at.desc()).all()
    superseded_ids = {str(record.supersedes_id) for record in records if record.supersedes_id}
    all_thread_ids = [str(record.thread_id) for record in records]
    all_sessions = UserSession.query.filter(
        UserSession.session_id.in_(all_thread_ids), UserSession.organization_id == str(org.id)
    ).all() if all_thread_ids else []
    all_session_by_thread = {str(row.session_id): row for row in sorted(all_sessions, key=lambda row: row.created_at or datetime.min)}
    records = [record for record in records if str(record.id) not in superseded_ids and can_read_record(record, user, membership=membership, session_row=all_session_by_thread.get(str(record.thread_id)), session_loaded=True) and (scope_context["scope"] == "organization" or str(record.user_id or "") == str(user.id))]
    thread_ids = [str(record.thread_id) for record in records]
    record_ids = [str(record.id) for record in records]
    sessions = [row for row in all_sessions if str(row.session_id) in set(thread_ids)]
    session_by_thread = {str(row.session_id): row for row in sorted(sessions, key=lambda row: row.created_at or datetime.min)}
    score_rows = Scorecard.query.filter(Scorecard.thread_id.in_(thread_ids)).all() if thread_ids else []
    score_by_thread = defaultdict(list)
    for row in score_rows:
        score_by_thread[str(row.thread_id)].append(row)
    signals = DecisionSignal.query.filter(DecisionSignal.decision_record_id.in_(record_ids), DecisionSignal.retracted_at.is_(None)).all() if record_ids else []
    signals_by_option = defaultdict(list)
    for signal in signals:
        signals_by_option[(str(signal.decision_record_id), str(signal.option_key or ""))].append(signal)
    decisions = OptionDecision.query.filter(OptionDecision.decision_record_id.in_(record_ids)).all() if record_ids else []
    decisions_by_option = defaultdict(list)
    for row in decisions:
        decisions_by_option[(str(row.decision_record_id), str(row.option_key))].append(row)
    resolved_events = defaultdict(dict)
    if thread_ids:
        for event in ChallengeEvent.query.filter(
            ChallengeEvent.thread_id.in_(thread_ids), ChallengeEvent.type == "assumption_resolved",
        ).all():
            if event.target_id:
                known = resolved_events[str(event.thread_id)].get(str(event.target_id))
                if known is None or (event.occurred_at and event.occurred_at < known):
                    resolved_events[str(event.thread_id)][str(event.target_id)] = event.occurred_at
    user_ids = {str(record.user_id) for record in records if record.user_id}
    people = User.query.filter(User.id.in_(user_ids)).all() if user_ids else []
    names = {str(person.id): str(person.name or person.email or "Unknown") for person in people}

    today = datetime.now(timezone.utc).replace(tzinfo=None)
    options = []
    decision_outcomes = []
    decision_lessons = []
    for record in records:
        decision_outcomes.extend(
            {"record_id": str(record.id), "decision_title": record.title, **entry}
            for entry in (record.outcomes or []) if isinstance(entry, dict)
        )
        decision_lessons.extend(
            {"record_id": str(record.id), "decision_title": record.title, **entry}
            for entry in (record.lessons_learned or []) if isinstance(entry, dict)
        )
        session = session_by_thread.get(str(record.thread_id))
        record_decisions = [row for values in decisions_by_option.values() for row in values if str(row.decision_record_id) == str(record.id)]
        record_signals = [row for values in signals_by_option.values() for row in values if str(row.decision_record_id) == str(record.id)]
        disposition = option_dispositions(
            record, session=session, scorecard_rows=score_by_thread.get(str(record.thread_id), []),
            decision_rows=record_decisions, decision_signal_rows=record_signals,
        )
        cards_by_key = defaultdict(list)
        for card in _cards(record):
            if _card_key(card):
                cards_by_key[_card_key(card)].append(card)
        plans = _plans(session)
        for state in disposition["options"]:
            cards = cards_by_key.get(state["option_key"], [])
            card = cards[-1] if cards else {}
            plan, basis = _basis(card, plans)
            tasks = _tasks(plan)
            decision_rows = sorted(decisions_by_option[(str(record.id), state["option_key"])], key=lambda row: row.decided_at or datetime.min)
            current_decision = decision_rows[-1] if decision_rows else None
            own_signals = signals_by_option[(str(record.id), state["option_key"])]
            option_signals = own_signals + signals_by_option[(str(record.id), "")]
            # Outcomes and lessons live on whichever version of the decision
            # they were recorded against; every version counts.
            outcome_entries = [entry for row in decision_rows for entry in (row.outcomes or []) if isinstance(entry, dict)]
            lesson_entries = [entry for row in decision_rows for entry in (row.lessons_learned or []) if isinstance(entry, dict)]
            gaps = _option_gaps(card, basis, tasks, resolved_events.get(str(record.thread_id)))
            conditions = _conditions(own_signals) if state["state"] == "pursued" else []
            override = current_decision.override_info if current_decision is not None and isinstance(current_decision.override_info, dict) else None
            verdict = current_decision.kit_verdict if current_decision is not None and isinstance(current_decision.kit_verdict, dict) else {}
            snapshot = verdict.get("recommendation_snapshot") if isinstance(verdict.get("recommendation_snapshot"), dict) else {}
            score = (basis or {}).get("jaspen_score") if basis else card.get("jaspen_score")
            evidence = (basis or {}).get("evidence_backed_pct") if basis else _evidence_pct(card)
            kind_key = str(record.decision_type or (record.record or {}).get("decision_kit") or "general")
            item = {
                "id": f"{record.id}:{state['option_key']}", "record_id": str(record.id), "thread_id": str(record.thread_id),
                "decision_title": record.title,
                "decision_kind_key": kind_key,
                # The kit's own display name, never its internal key.
                "decision_kind": (get_decision_kit(kind_key) or {}).get("label") or ("General decision" if kind_key in {"", "general"} else kind_key.replace("_", " ").capitalize()),
                "owner": {"id": str(record.user_id or "") or None, "name": names.get(str(record.user_id), "Former member")},
                "option_key": state["option_key"], "option_name": state.get("option_name") or card.get("name") or "Option",
                "state": state["state"], "state_source": state["state_source"], "state_since": state["state_since"], "still_evaluating": state["still_evaluating"],
                "first_scored_at": state["first_scored_at"], "first_plan_at": state["first_plan_at"], "score": score, "score_band": (basis or {}).get("score_category") or card.get("score_category"),
                "evidence_backed_pct": evidence, "basis_source": "plan_snapshot" if basis else "current",
                "history": state["history"], "decision_basis": basis, "gaps": gaps, "required_checks": card.get("gates") or [],
                "plan": {"created_at": plan.get("created_at"), "tasks_total": len(tasks), "tasks_completed": sum(str(task.get("status") or "").lower() in DONE for task in tasks), "scorecard_id": (basis or {}).get("scorecard_id")} if plan else None,
                "card": card, "tasks": tasks, "has_success_measure": any(signal.kind == "success_measure" for signal in option_signals),
                "outcomes": outcome_entries, "lessons": lesson_entries,
                "conditions": conditions,
                "against_recommendation": (
                    {"override_of": override.get("override_of"), "jaspen_recommendation": snapshot.get("label") or (card.get("recommendation") or {}).get("label"),
                     "failed_check_labels": list(override.get("failed_check_labels") or [])}
                    if override and state["state"] == "pursued" else None
                ),
                "success_review_by": sorted(
                    value for value in (_iso(_dt((signal.structured or {}).get("review_by"))) for signal in own_signals if signal.kind == "success_measure" and isinstance(signal.structured, dict)) if value
                ),
            }
            item["signals"] = option_signals
            item["triggers"] = _attention(item, today)
            item.pop("signals", None)
            item.pop("card", None)
            options.append(item)

    cohort_days = filters.get("days")
    floor = today.date().toordinal() - int(cohort_days) if str(cohort_days or "").isdigit() else None
    def matches(item):
        first = _dt(item["first_scored_at"])
        if floor is not None and (not first or first.date().toordinal() < floor): return False
        if filters.get("state") and item["state"] != filters["state"]: return False
        if filters.get("kind") and item["decision_kind"] != filters["kind"]: return False
        if filters.get("member") and item["owner"]["id"] != filters["member"]: return False
        if filters.get("attention") and not item["triggers"]: return False
        if filters.get("gap") and not any(gap["key"] == filters["gap"] for gap in item["gaps"]): return False
        query = str(filters.get("search") or "").casefold()
        return not query or query in f"{item['option_name']} {item['decision_title']}".casefold()
    options = [item for item in options if matches(item)]
    counts = {state: sum(item["state"] == state for item in options) for state in ("pursued", "not_pursued", "open", "archived")}
    total = len(options)
    avg_hours = []
    for item in options:
        start, end = _dt(item["first_scored_at"]), _dt(item["first_plan_at"])
        if start and end: avg_hours.append(max(0, (end - start).total_seconds() / 3600))
    source_breakdown = {
        state: {
            "stated": sum(item["state"] == state and item["state_source"] not in {"plan_created"} for item in options),
            "from_plan": sum(item["state"] == state and item["state_source"] == "plan_created" for item in options),
        }
        for state in ("pursued", "not_pursued", "open", "archived")
    }
    open_items = [item for item in options if item["state"] == "open"]
    open_dates = [_dt(item["first_scored_at"]) for item in open_items]
    open_dates = [value for value in open_dates if value]
    activity = {
        "total_scored": _metric(total, denominator=total, coverage=total),
        **{state: _metric(value, denominator=total, coverage=total, source_breakdown=source_breakdown[state]) for state, value in counts.items()},
        "reconciles": sum(counts.values()) == total,
        "average_time_to_plan_hours": _metric(round(sum(avg_hours) / len(avg_hours), 2) if avg_hours else None, numerator=len(avg_hours), denominator=sum(item["state"] == "pursued" for item in options), coverage=len(avg_hours), unavailable_reason=None if avg_hours else "no_plans", within_one_hour=sum(value <= 1 for value in avg_hours)),
        "needs_attention": [item for item in options if item["triggers"]],
        "plans": [item for item in options if item["plan"] and item["state"] == "pursued"],
        "open_oldest_age_days": _metric(
            (today.date() - min(open_dates).date()).days if open_dates else None,
            numerator=len(open_dates), denominator=len(open_items), coverage=len(open_dates),
            unavailable_reason=None if open_dates else "no_open_scored_dates",
        ),
        "open_still_evaluating": _metric(
            sum(item["still_evaluating"] for item in open_items), denominator=len(open_items), coverage=len(open_items),
        ),
    }
    flow = defaultdict(lambda: {"scored": 0, "decided": 0})
    by_kind = defaultdict(lambda: {"scored": 0, "pursued": 0, "not_pursued": 0, "open": 0, "archived": 0, "hours": []})
    for item in options:
        first = _dt(item["first_scored_at"])
        if first:
            week = (first.date() - timedelta(days=first.weekday())).isoformat()
            flow[week]["scored"] += 1
        since = _dt(item["state_since"])
        if since and item["state"] in {"pursued", "not_pursued"}:
            week = since.date() - timedelta(days=since.weekday())
            flow[week.isoformat()]["decided"] += 1
        kind = by_kind[item["decision_kind"]]; kind["scored"] += 1; kind[item["state"]] += 1
    activity["flow"] = [{"date": key, **flow[key]} for key in sorted(flow)]
    activity["by_kind"] = [{"kind": key, **{k: v for k, v in value.items() if k != "hours"}} for key, value in sorted(by_kind.items())]

    band_rows = []
    for state in ("pursued", "not_pursued", "open"):
        items = [item for item in options if item["state"] == state]
        bands = defaultdict(int)
        for item in items: bands[item["score_band"] or "Not available"] += 1
        band_rows.append({"state": state, "total": len(items), "bands": dict(bands), "mostly_assumed": sum(item["evidence_backed_pct"] is not None and item["evidence_backed_pct"] < 50 for item in items)})
    gaps = [gap for item in options if item["state"] == "pursued" for gap in item["gaps"]]
    stages = {"identified": len(gaps), "task_created": sum(gap["task_created"] for gap in gaps), "task_completed": sum(gap["task_completed"] for gap in gaps), "resolved": sum(gap["resolved"] for gap in gaps), "result": sum(bool(item["outcomes"]) for item in options if item["state"] == "pursued")}
    month_values = defaultdict(list)
    for item in options:
        if item["state"] == "pursued" and item["decision_basis"] and item["evidence_backed_pct"] is not None:
            captured = str(item["decision_basis"].get("captured_at") or "")[:7]
            if captured: month_values[captured].append(item["evidence_backed_pct"])
    resolved_before = defaultdict(lambda: [0, 0])
    for item in options:
        if item["state"] == "pursued" and item["decision_basis"]:
            captured = str(item["decision_basis"].get("captured_at") or "")[:7]
            plan_at = _dt((item["plan"] or {}).get("created_at"))
            for gap in item["gaps"]:
                if captured:
                    resolved_before[captured][1] += 1
                    resolved_at = _dt(gap.get("resolved_at"))
                    if resolved_at and plan_at and resolved_at < plan_at:
                        resolved_before[captured][0] += 1
    evidence_trend = [
        {"month": month, "evidence_backed_pct": round(sum(values) / len(values), 1), "n": len(values),
         "gaps_resolved_before_plan_pct": (round(100 * resolved_before[month][0] / resolved_before[month][1], 1) if resolved_before[month][1] else None),
         "gaps_identified": resolved_before[month][1]}
        for month, values in sorted(month_values.items())
    ]
    recurring = defaultdict(lambda: {"decisions": set(), "resolved": 0, "label": "", "resolution": None})
    excluded_custom_gaps = 0
    for item in options:
        for gap in item["gaps"]:
            key = gap["key"] if str(item["decision_kind_key"]).startswith("rfp") else gap.get("group")
            if not key:
                excluded_custom_gaps += 1
                continue
            entry = recurring[(item["decision_kind"], key)]; entry["decisions"].add(item["record_id"]); entry["resolved"] += int(gap["resolved"]); entry["label"] = gap["label"]; entry["resolution"] = gap.get("resolution") or entry["resolution"]
    decisions_by_kind = defaultdict(set)
    for item in options:
        decisions_by_kind[item["decision_kind"]].add(item["record_id"])
    recurring_rows = [{"kind": kind, "key": key, "label": value["label"], "decisions_affected": len(value["decisions"]), "decisions_total": len(decisions_by_kind[kind]), "resolved_later": value["resolved"], "next_step_on_record": value["resolution"]} for (kind, key), value in recurring.items()]
    pursued = [item for item in options if item["state"] == "pursued"]
    def _statuses(item):
        return [str(outcome.get("status") or "").lower() for outcome in item["outcomes"]]
    outcome_stages = {
        "pursued": len(pursued),
        "success_measure_captured": sum(item["has_success_measure"] for item in pursued),
        "implementation_complete": sum(bool(item["plan"] and item["plan"]["tasks_total"] and item["plan"]["tasks_total"] == item["plan"]["tasks_completed"]) for item in pursued),
        "awaiting_measurement": sum(
            not any(status in MEASURED for status in _statuses(item))
            and ("too_early" in _statuses(item) or any(_dt(value) and _dt(value).date() >= today.date() for value in item["success_review_by"]))
            for item in pursued
        ),
        "outcomes_recorded": len(decision_outcomes) + sum(len(item["outcomes"]) for item in pursued),
        "measured": sum(any(status in MEASURED for status in _statuses(item)) for item in pursued),
        "measured_by_status": {status: sum(status in _statuses(item) for item in pursued) for status in sorted(MEASURED)},
        "met_expectation": sum(any(outcome.get("objective_met") is True for outcome in item["outcomes"]) for item in pursued),
        "lessons": len(decision_lessons) + sum(len(item["lessons"]) for item in pursued),
        "latest_lesson": max(
            ({"option_id": item["id"], "option_name": item["option_name"], "recorded_at": lesson.get("recorded_at"), "lesson": lesson.get("lesson") or lesson.get("summary")}
             for item in pursued for lesson in item["lessons"]),
            key=lambda entry: str(entry.get("recorded_at") or ""), default=None,
        ),
    }
    latest_decision_lesson = max(decision_lessons, key=lambda entry: str(entry.get("recorded_at") or ""), default=None)
    if latest_decision_lesson and (
        outcome_stages["latest_lesson"] is None
        or str(latest_decision_lesson.get("recorded_at") or "")
        > str(outcome_stages["latest_lesson"].get("recorded_at") or "")
    ):
        outcome_stages["latest_lesson"] = {
            "option_id": None,
            "option_name": latest_decision_lesson["decision_title"],
            "recorded_at": latest_decision_lesson.get("recorded_at"),
            "lesson": latest_decision_lesson.get("lesson") or latest_decision_lesson.get("summary"),
        }
    summary = []
    if activity["needs_attention"]: summary.append({"kind": "exception", "option_id": activity["needs_attention"][0]["id"], "count": len(activity["needs_attention"]), "trigger_kind": activity["needs_attention"][0]["triggers"][0]["kind"]})
    assumed = [item for item in pursued if item["evidence_backed_pct"] is not None and item["evidence_backed_pct"] < 50]
    if assumed: summary.append({"kind": "pattern", "pattern": "mostly_assumed_pursuits", "count": len(assumed), "total": len(pursued)})
    top_recurring = max(recurring_rows, key=lambda row: row["decisions_affected"], default=None)
    if top_recurring and top_recurring["decisions_affected"] >= 2:
        summary.append({"kind": "pattern", "pattern": "recurring_gap", "gap_key": top_recurring["key"], "label": top_recurring["label"],
                        "decision_kind": top_recurring["kind"], "decisions_affected": top_recurring["decisions_affected"],
                        "decisions_total": top_recurring["decisions_total"]})
    if gaps: summary.append({"kind": "follow_through", "identified": len(gaps), "tasks_completed": stages["task_completed"], "resolved": stages["resolved"]})
    if len(evidence_trend) >= 2 and evidence_trend[-1]["evidence_backed_pct"] != evidence_trend[0]["evidence_backed_pct"]:
        summary.append({"kind": "improvement", "metric": "evidence_at_commitment", "from_month": evidence_trend[0]["month"],
                        "from_pct": evidence_trend[0]["evidence_backed_pct"], "to_month": evidence_trend[-1]["month"],
                        "to_pct": evidence_trend[-1]["evidence_backed_pct"]})
    rank = {"exception": 0, "pattern": 1, "follow_through": 2, "improvement": 3}
    summary = sorted(summary, key=lambda finding: rank.get(finding["kind"], 9))[:3]

    active_members = OrganizationMember.query.filter_by(organization_id=org.id, status="active").all()
    member_ids = [str(row.user_id) for row in active_members if row.user_id]
    members = User.query.filter(User.id.in_(member_ids)).all() if member_ids else []
    page = max(int(filters.get("page") or 1), 1); per_page = min(max(int(filters.get("per_page") or 25), 1), 100)
    page_rows = options[(page - 1) * per_page:page * per_page]
    previous_record_id = None
    for item in page_rows:
        item["show_group_heading"] = item["record_id"] != previous_record_id
        previous_record_id = item["record_id"]
    return {
        "schema_version": 3, "organization": {"id": org.id, "name": org.name}, "scope": scope_context["scope"], "requested_scope": scope_context["requested_scope"],
        "can_manage": scope_context["can_manage"], "can_view_organization": scope_context["can_view_organization"], "show_scope_control": bool(scope_context.get("show_scope_control", scope_context["can_view_organization"])),
        "summary": summary, "activity": activity,
        "effectiveness": {"acting_on": band_rows, "gap_follow_through": stages, "evidence_at_commitment": _metric(evidence_trend if len(evidence_trend) >= 2 else None, numerator=len(evidence_trend), denominator=2, coverage=len(evidence_trend), unavailable_reason=None if len(evidence_trend) >= 2 else "insufficient_months", points=evidence_trend), "recurring_gaps": recurring_rows, "recurring_gaps_excluded": excluded_custom_gaps, "outcomes": outcome_stages},
        "register": {"rows": page_rows, "total": total, "page": page, "per_page": per_page, "pages": max(1, (total + per_page - 1) // per_page)},
        "facets": {"states": ["pursued", "not_pursued", "open", "archived"], "kinds": sorted({item["decision_kind"] for item in options}), "members": [{"id": str(person.id), "name": str(person.name or person.email)} for person in members]},
    }
