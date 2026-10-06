"""Decision-to-execution lineage assembly, validation, and scheduling."""

from datetime import date, datetime, timedelta

VALID_LINEAGE_TYPES = {"condition", "gate", "requirement", "weak_criterion", "risk", "recommendation", "decision_commitment"}


def _value(attributes, key):
    entry = (attributes or {}).get(key)
    return entry.get("value") if isinstance(entry, dict) else entry


def build_lineage_sources(scorecard, kit=None, decision_record=None):
    scorecard = scorecard if isinstance(scorecard, dict) else {}
    sources = []
    recommendation = scorecard.get("recommendation") if isinstance(scorecard.get("recommendation"), dict) else {}
    for item in recommendation.get("conditions") or []:
        if isinstance(item, dict) and item.get("id"):
            sources.append({"type": "condition", "ref": str(item["id"]), "label": str(item.get("text") or item["id"]), "required": True})
    for gate in scorecard.get("gates") or []:
        if isinstance(gate, dict) and gate.get("status") in {"fail", "unknown"}:
            sources.append({"type": "gate", "ref": str(gate.get("key") or gate.get("label")), "label": str(gate.get("label") or gate.get("key")), "required": True})
    attributes = scorecard.get("attributes") if isinstance(scorecard.get("attributes"), dict) else {}
    bindings = (kit or {}).get("plan_bindings") if isinstance((kit or {}).get("plan_bindings"), dict) else {}
    for key in bindings.get("requirements") or []:
        raw = _value(attributes, key)
        entries = list(raw.items()) if isinstance(raw, dict) else list(enumerate(raw)) if isinstance(raw, list) else []
        for index, value in entries:
            label = value.get("label") if isinstance(value, dict) else value
            if label:
                sources.append({"type": "requirement", "ref": f"{key}[{index}]", "label": str(label), "required": True})
    dims = scorecard.get("dimensions") if isinstance(scorecard.get("dimensions"), dict) else {}
    for key, dim in dims.items():
        if isinstance(dim, dict) and float(dim.get("score") or 0) < 75:
            sources.append({"type": "weak_criterion", "ref": str(key), "label": str(dim.get("label") or key), "required": True})
    for index, risk in enumerate(scorecard.get("top_risks") or scorecard.get("risks") or []):
        label = risk.get("text") or risk.get("risk") if isinstance(risk, dict) else risk
        ref = risk.get("id") if isinstance(risk, dict) else None
        if label:
            sources.append({"type": "risk", "ref": str(ref or f"risk_{index + 1}"), "label": str(label), "required": True})
    for index, rec in enumerate(scorecard.get("recommendations") or []):
        label = rec.get("text") or rec.get("recommendation") if isinstance(rec, dict) else rec
        ref = rec.get("id") if isinstance(rec, dict) else None
        if label:
            sources.append({"type": "recommendation", "ref": str(ref or f"recommendation_{index + 1}"), "label": str(label), "required": True})
    if decision_record:
        verdict = str((decision_record or {}).get("final_decision") or "").strip()
        if verdict:
            sources.append({"type": "decision_commitment", "ref": str((decision_record or {}).get("id") or "human_decision"), "label": verdict, "required": True})
    seen, result = set(), []
    for item in sources:
        identity = (item["type"], item["ref"])
        if identity not in seen:
            result.append(item); seen.add(identity)
    return result


def validate_plan_lineage(plan, sources):
    plan = dict(plan) if isinstance(plan, dict) else {}
    valid = {(item["type"], str(item["ref"])): item for item in sources or [] if item.get("type") in VALID_LINEAGE_TYPES and item.get("ref")}
    tasks, dropped, covered = [], [], set()
    phase_source = plan.get("phases") if isinstance(plan.get("phases"), list) else None
    raw_tasks = []
    if phase_source is not None:
        for phase in phase_source:
            if not isinstance(phase, dict):
                continue
            for task in phase.get("tasks") or []:
                if isinstance(task, dict):
                    raw_tasks.append({**task, "phase": task.get("phase") or phase.get("name") or "Execution"})
    else:
        raw_tasks = [item for item in plan.get("tasks") or [] if isinstance(item, dict)]
    for task in raw_tasks:
        normalized = []
        task_links = set()
        for link in task.get("lineage") or []:
            if not isinstance(link, dict):
                continue
            identity = (str(link.get("type") or ""), str(link.get("ref") or ""))
            if identity in valid:
                source = valid[identity]
                if identity not in task_links:
                    normalized.append({"type": identity[0], "ref": identity[1], "label": source.get("label")})
                    task_links.add(identity)
                covered.add(identity)
        if normalized:
            tasks.append({**task, "lineage": normalized})
        else:
            dropped.append(str(task.get("id") or task.get("title") or "unlinked task"))
    missing = [item for identity, item in valid.items() if item.get("required") and identity not in covered]
    if not tasks or missing:
        return None, {"code": "invalid_plan_lineage", "dropped_tasks": dropped, "missing_sources": missing}
    # Provider task ids and dependencies are presentation mechanics, not
    # decision lineage. Canonicalize duplicates and discard unknown, self, or
    # forward dependencies so scheduling cannot fail on junk graph edges.
    used, id_map = set(), {}
    for index, task in enumerate(tasks):
        raw_id = str(task.get("id") or f"task-{index + 1}").strip()
        canonical = raw_id
        suffix = 2
        while canonical in used:
            canonical = f"{raw_id}-{suffix}"
            suffix += 1
        used.add(canonical)
        id_map.setdefault(raw_id, canonical)
        task["id"] = canonical
    prior = set()
    for task in tasks:
        dependencies = task.get("depends_on") or task.get("dependencies") or []
        normalized_dependencies = []
        for dependency in dependencies if isinstance(dependencies, list) else []:
            target = id_map.get(str(dependency))
            if target and target in prior and target not in normalized_dependencies:
                normalized_dependencies.append(target)
        task["dependencies"] = normalized_dependencies
        task.pop("depends_on", None)
        prior.add(task["id"])
    return {**plan, "tasks": tasks, "phases": []}, {"dropped_tasks": dropped, "missing_sources": []}



def assign_team_owners(plan, team):
    members = [dict(item) for item in (team or []) if isinstance(item, dict) and (item.get("name") or item.get("email"))]
    tasks = []
    for raw in plan.get("tasks") or []:
        task = dict(raw)
        if task.get("owner"):
            # Keep a supplied owner only when it is a recorded team member.
            names = {str(item.get("name") or "").strip().lower() for item in members}
            if str(task.get("owner") or "").strip().lower() not in names:
                task["owner"] = "Unassigned"
        else:
            role = str(task.get("suggested_role") or "").strip().lower()
            match = next((item for item in members if role and role in str(item.get("role") or "").strip().lower()), None)
            task["owner"] = str((match or {}).get("name") or "Unassigned")
        tasks.append(task)
    return {**plan, "tasks": tasks}

def _business_shift(day, amount):
    direction = 1 if amount >= 0 else -1
    remaining = abs(int(amount))
    current = day
    while remaining:
        current += timedelta(days=direction)
        if current.weekday() < 5:
            remaining -= 1
    return current


def schedule_backward(plan, deadline, *, buffer_days=1):
    try:
        deadline_date = datetime.strptime(str(deadline), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return plan
    tasks = [dict(item) for item in (plan.get("tasks") or []) if isinstance(item, dict)]
    by_id = {str(item.get("id")): item for item in tasks if item.get("id")}
    dependents = {key: [] for key in by_id}
    for task in tasks:
        for dep in task.get("depends_on") or task.get("dependencies") or []:
            if str(dep) in dependents:
                dependents[str(dep)].append(str(task.get("id")))
    target = _business_shift(deadline_date, -max(0, int(buffer_days)))
    scheduled = {}
    visiting = set()
    def place(task_id):
        if task_id in scheduled:
            return scheduled[task_id]
        if task_id in visiting:
            raise ValueError("circular_dependencies")
        visiting.add(task_id)
        child_starts = [place(child)[0] for child in dependents.get(task_id, [])]
        due = _business_shift(min(child_starts), -1) if child_starts else target
        duration = max(1, int(by_id[task_id].get("estimated_days") or by_id[task_id].get("timeline_days") or 1))
        start = _business_shift(due, -(duration - 1))
        scheduled[task_id] = (start, due)
        visiting.remove(task_id)
        return start, due
    try:
        for task_id in by_id:
            place(task_id)
    except ValueError:
        return {**plan, "schedule_error": "circular_dependencies"}
    today = date.today()
    overrun = []
    for task in tasks:
        task_id = str(task.get("id") or "")
        if task_id in scheduled:
            start, due = scheduled[task_id]
            task["start_date"], task["due_date"] = start.isoformat(), due.isoformat()
            if start < today:
                overrun.append(task.get("title") or task_id)
    output = {**plan, "tasks": tasks, "deadline": deadline_date.isoformat(), "schedule_mode": "backward", "deadline_buffer_business_days": buffer_days}
    if overrun:
        output["compression_warning"] = {"message": "The derived work does not fit before the deadline.", "tasks": overrun, "shortfall_business_days": max(1, (today - min(scheduled[item][0] for item in scheduled)).days)}
    return output
