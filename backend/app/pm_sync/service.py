import re
from datetime import datetime, timedelta

from app import db
from app.models import ConnectorSyncLog
from app.models_pm_sync import PmSyncBinding, PmSyncLink
from app.pm_sync import jira_adapter
from app.scenarios_store import load_scenarios_data

MODES = {"two_way", "push_only"}
POLICIES = {"latest_wins", "prefer_external", "prefer_jaspen", "manual_review"}
STATUSES = {"active", "paused", "error", "partial", "disconnected"}
GENERIC_PHASE_NAMES = {"", "unphased", "execution", "execution plan", "generated plan", "plan"}


def _now():
    return datetime.utcnow()


def get_plan(user_id, thread_id, plan_key):
    thread = load_scenarios_data(user_id).get(thread_id)
    if not isinstance(thread, dict):
        raise LookupError("Thread not found.")
    by_scorecard = thread.get("wbs_by_scorecard") if isinstance(thread.get("wbs_by_scorecard"), dict) else {}
    plan = by_scorecard.get(plan_key) if plan_key else None
    if not isinstance(plan, dict):
        active_key = str(thread.get("active_execution_scorecard_id") or "").strip()
        if plan_key and active_key and plan_key != active_key:
            raise LookupError("Execution plan not found for this decision.")
        plan = thread.get("project_wbs")
    if not isinstance(plan, dict):
        raise LookupError("Execution plan not found.")
    resolved_key = str(plan_key or plan.get("scorecard_id") or thread.get("active_execution_scorecard_id") or "").strip()
    if not resolved_key:
        raise ValueError("This execution plan needs a stable plan key before it can be sent.")
    return plan, resolved_key


def _clean_phase(value):
    return str(value or "").strip() or "Unphased"


def _meaningful_phase(value):
    normalized = re.sub(r"\s+", " ", _clean_phase(value).lower()).strip()
    return normalized not in GENERIC_PHASE_NAMES and not re.fullmatch(r"phase\s*[0-9a-z]+", normalized)


def phase_groups(plan):
    tasks = [task for task in (plan.get("tasks") or []) if isinstance(task, dict) and str(task.get("id") or "").strip()]
    phase_order = list(dict.fromkeys(_clean_phase(task.get("phase")) for task in tasks))
    meaningful = [phase for phase in phase_order if _meaningful_phase(phase)]
    plan_title = str(plan.get("name") or plan.get("title") or "Execution plan").strip() or "Execution plan"
    if len(meaningful) < 2:
        stable_key = phase_order[0] if phase_order else "Unphased"
        return [{"key": stable_key, "title": plan_title, "tasks": tasks}] if tasks else []
    groups = []
    for phase in phase_order:
        phase_tasks = [task for task in tasks if _clean_phase(task.get("phase")) == phase]
        groups.append({"key": phase, "title": phase if _meaningful_phase(phase) else plan_title, "tasks": phase_tasks})
    return groups


def _phase_snapshot(group, binding):
    fields = jira_adapter.phase_fields(group["title"], binding, group["tasks"], f"phase:{group['key']}")
    start_field = str((binding.config or {}).get("start_date_field_id") or "").strip()
    return {
        "title": fields.get("summary"),
        "start_date": fields.get(start_field) if start_field else None,
        "due_date": fields.get("duedate"),
    }


def ensure_start_date_field(binding, config):
    current = str((binding.config or {}).get("start_date_field_id") or "").strip()
    if current:
        return current
    try:
        discovered = jira_adapter.discover_start_date_field(config)
    except Exception:
        discovered = None
    if discovered:
        binding.config = {**(binding.config or {}), "start_date_field_id": discovered}
        db.session.flush()
    return discovered


def preview(plan, group_under_epics=True):
    tasks = [task for task in (plan.get("tasks") or []) if isinstance(task, dict) and str(task.get("id") or "").strip()]
    groups = phase_groups(plan) if group_under_epics else []
    dependencies = sum(len(task.get("depends_on") or []) for task in tasks)
    unresolved = len({str(task.get("owner") or "").strip() for task in tasks if str(task.get("owner") or "").strip()})
    missing_start_dates = sum(1 for task in tasks if not jira_adapter.effective_start_date(task))
    structures = [
        f"Creates epic '{group['title']}' with {len(group['tasks'])} task{'s' if len(group['tasks']) != 1 else ''}"
        for group in groups
    ] if group_under_epics else [f"Creates {len(tasks)} task{'s' if len(tasks) != 1 else ''} without epics"]
    if structures:
        structures[-1] += f", {dependencies} 'Blocks' link{'s' if dependencies != 1 else ''}."
    return {
        "epics": len(groups),
        "issues": len(tasks),
        "dependencies": dependencies,
        "unmapped_owners": unresolved,
        "tasks_without_start_date": missing_start_dates,
        "structure": " ".join(structures),
    }


def create_binding(user, payload):
    connector_id = str(payload.get("connector_id") or "jira_sync").strip().lower()
    if connector_id != "jira_sync":
        raise ValueError("This milestone supports Jira only.")
    thread_id = str(payload.get("thread_id") or "").strip()
    requested_plan_key = str(payload.get("plan_key") or "").strip()
    project_key = str(payload.get("external_container_id") or payload.get("project_key") or "").strip()
    mode = str(payload.get("mode") or "").strip().lower()
    policy = str(payload.get("conflict_policy") or "").strip().lower()
    if not thread_id or not project_key:
        raise ValueError("Thread and Jira project are required.")
    if mode not in MODES:
        raise ValueError("Choose a sync mode before sending.")
    if policy not in POLICIES:
        raise ValueError("Choose a conflict policy before sending.")
    plan, plan_key = get_plan(user.id, thread_id, requested_plan_key)
    jira = jira_adapter.assert_connected(user.id, project_key)
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    try:
        start_date_field_id = jira_adapter.discover_start_date_field(jira)
    except Exception:
        start_date_field_id = None
    config = {
        "task_issue_type": str(config.get("task_issue_type") or "Task"),
        "group_under_epics": bool(config.get("group_under_epics", True)),
        "priority_map": config.get("priority_map") if isinstance(config.get("priority_map"), dict) else {},
        "status_map": config.get("status_map") if isinstance(config.get("status_map"), dict) else {},
        "start_date_field_id": str(config.get("start_date_field_id") or start_date_field_id or ""),
    }
    binding = PmSyncBinding.query.filter_by(thread_id=thread_id, plan_key=plan_key, connector_id=connector_id).first()
    if binding:
        raise ValueError("This execution plan is already bound to Jira.")
    binding = PmSyncBinding(
        user_id=user.id,
        organization_id=getattr(user, "active_organization_id", None),
        thread_id=thread_id,
        plan_key=plan_key,
        connector_id=connector_id,
        external_container_id=project_key,
        external_container_url=f"{jira['base_url']}/browse/{project_key}",
        mode=mode,
        conflict_policy=policy,
        field_policy_overrides=payload.get("field_policy_overrides") if isinstance(payload.get("field_policy_overrides"), dict) else {},
        policy_set_by_user_id=user.id,
        policy_set_at=_now(),
        config=config,
        user_map={},
        status="active",
    )
    db.session.add(binding)
    db.session.commit()
    return binding, plan


def _snapshot(task):
    def normalized(value):
        if value is None:
            return None
        if isinstance(value, str):
            return value.strip() or None
        if isinstance(value, (list, tuple)):
            values = [normalized(item) for item in value]
            values = [item for item in values if item is not None]
            return values or None
        return value
    return {
        key: normalized(task.get(key)) for key in (
            "title", "description", "rationale", "owner", "owner_email", "status",
            "priority", "start_date", "due_date", "phase", "depends_on", "lineage", "updated_at",
        )
    }


def _task_synced_fields(task, binding):
    """Fields Jira was actually sent, separate from values held by Jaspen."""
    fields = {"title", "description", "status", "due_date"}
    if (binding.config or {}).get("start_date_field_id") and jira_adapter.effective_start_date(task):
        fields.add("start_date")
    if not str(task.get("owner") or "").strip() and not str(task.get("owner_email") or "").strip():
        fields.update({"owner", "owner_email"})
    else:
        user_map = binding.user_map if isinstance(binding.user_map, dict) else {}
        if user_map.get(str(task.get("owner_email") or "")) or user_map.get(str(task.get("owner") or "")):
            fields.update({"owner", "owner_email"})
    return sorted(fields)


def _created_task_snapshot(config, binding, issue_key, task):
    """Capture Jira's actual post-create state without adopting its defaults."""
    local = _snapshot(task)
    local["start_date"] = jira_adapter.effective_start_date(task)
    local["_synced_fields"] = _task_synced_fields(task, binding)
    try:
        remote = jira_adapter.JiraProvider().get_item(config, binding, issue_key)
    except Exception:
        return local
    values = remote.get("values") if isinstance(remote, dict) and isinstance(remote.get("values"), dict) else {}
    if remote.get("deleted") or (not remote.get("version") and not any(value not in (None, "", []) for value in values.values())):
        return local
    actual = _snapshot(values)
    actual["_synced_fields"] = sorted(set(remote.get("supported_fields") or []) & {
        "title", "description", "owner", "owner_email", "status", "start_date", "due_date",
    })
    preserved = [
        field for field in ("owner", "owner_email")
        if local.get(field) is None and actual.get(field) is not None
    ]
    if preserved:
        # Top-level values are the actual Jira baseline. The marker tells the
        # three-way comparer that Jaspen intentionally remains unassigned.
        actual["_preserve_local_empty_fields"] = preserved
    return actual


def _sync_phases(binding, plan, config, existing, result):
    if not bool((binding.config or {}).get("group_under_epics", True)):
        return {}
    task_parents = {}
    for group in phase_groups(plan):
        phase_key = group["key"]
        link = existing.get(("phase", phase_key))
        issue_key = str(link.external_id if link else "").strip()
        entity_id = f"phase:{phase_key}"
        desired = _phase_snapshot(group, binding)
        try:
            if not issue_key:
                recovered = _recover_or_none(config, binding, f"phase:{phase_key}")
                if recovered:
                    issue_key = str(recovered.get("key") or "")
                else:
                    created, _ = jira_adapter.request(
                        config, "POST", "/rest/api/3/issue",
                        {"fields": jira_adapter.phase_fields(group["title"], binding, group["tasks"], entity_id)}
                    )
                    issue_key = str(created.get("key") or "")
                    result["created"] += 1
                if not issue_key:
                    raise ValueError("Jira did not return an epic key.")
                # The Jira object now exists. Persist its key before optional
                # property/remote-link calls so retry can never duplicate it.
                _upsert_link(binding, "phase", phase_key, issue_key, snapshot=desired)
                db.session.commit()
                jira_adapter.set_identity(config, binding, issue_key, "phase", entity_id)
            else:
                previous = link.base_snapshot if isinstance(link.base_snapshot, dict) else {}
                if previous != desired:
                    fields = jira_adapter.phase_fields(group["title"], binding, group["tasks"], entity_id)
                    jira_adapter.request(config, "PUT", f"/rest/api/3/issue/{issue_key}", {"fields": jira_adapter.update_fields(fields)})
                    result["updated"] += 1
                jira_adapter.ensure_recovery_identity(config, binding, issue_key, entity_id)
                if link.last_error:
                    jira_adapter.set_identity(config, binding, issue_key, "phase", entity_id)
            _upsert_link(binding, "phase", phase_key, issue_key, snapshot=desired)
            db.session.commit()
            for task in group["tasks"]:
                task_parents[str(task.get("id"))] = issue_key
        except Exception as exc:
            db.session.rollback()
            # Jira may have created the epic before its Jaspen identity link
            # failed. Keep that external key so a retry repairs the identity
            # and updates the same epic instead of creating a duplicate.
            if issue_key:
                _upsert_link(
                    binding, "phase", phase_key, issue_key,
                    snapshot=desired, state="active", error=exc,
                )
                db.session.commit()
                for task in group["tasks"]:
                    task_parents[str(task.get("id"))] = issue_key
            result["failed"] += 1
            result["errors"].append({"entity_type": "phase", "jaspen_id": phase_key, "error": str(exc)})
    return task_parents


def _record_log(binding, trigger, result):
    errors = result.get("errors") if isinstance(result.get("errors"), list) else []
    log = ConnectorSyncLog(
        user_id=binding.user_id,
        connector_id=binding.connector_id,
        thread_id=binding.thread_id,
        action="pm_sync_push",
        status="success" if not errors else ("partial" if result.get("created") or result.get("updated") else "failed"),
        items_synced=int(result.get("created") or 0) + int(result.get("updated") or 0),
        error_message=("; ".join(str(item.get("error") or "") for item in errors)[:2000] or None),
        sync_metadata={
            "binding_id": binding.id,
            "direction": "push",
            "trigger": trigger,
            "counts": {key: int(result.get(key) or 0) for key in ("created", "updated", "dependencies", "failed")},
            "errors": errors[:50],
        },
    )
    db.session.add(log)


def _upsert_link(binding, entity_type, jaspen_id, external_id=None, parent_id=None, snapshot=None, state="active", error=None):
    link = PmSyncLink.query.filter_by(binding_id=binding.id, entity_type=entity_type, jaspen_id=str(jaspen_id)).first()
    if not link:
        link = PmSyncLink(binding_id=binding.id, entity_type=entity_type, jaspen_id=str(jaspen_id))
        db.session.add(link)
    if external_id:
        link.external_id = str(external_id)
    link.external_parent_id = str(parent_id) if parent_id else None
    link.base_snapshot = snapshot or {}
    link.jaspen_version = str((snapshot or {}).get("updated_at") or "") or None
    link.state = state
    link.last_error = str(error)[:4000] if error else None
    link.last_synced_at = _now()
    return link


def _recover_or_none(config, binding, entity_id):
    try:
        return jira_adapter.recover_issue(config, binding, entity_id)
    except Exception:
        return None


def push_binding(binding, plan=None, trigger="send"):
    if binding.status == "paused":
        raise ValueError("This Jira sync is paused.")
    if plan is None:
        plan, _ = get_plan(binding.user_id, binding.thread_id, binding.plan_key)
    config = jira_adapter.assert_connected(binding.user_id, binding.external_container_id)
    ensure_start_date_field(binding, config)
    tasks = [task for task in (plan.get("tasks") or []) if isinstance(task, dict) and str(task.get("id") or "").strip()]
    existing = {
        (link.entity_type, link.jaspen_id): link
        for link in PmSyncLink.query.filter_by(binding_id=binding.id).all()
    }
    result = {"created": 0, "updated": 0, "dependencies": 0, "failed": 0, "errors": []}
    task_parents = _sync_phases(binding, plan, config, existing, result)

    pending = []
    for task in tasks:
        task_id = str(task["id"])
        link = existing.get(("task", task_id))
        issue_key = str(link.external_id if link else "").strip()
        parent = task_parents.get(task_id)
        fields = jira_adapter.task_fields(task, binding, parent)
        if not issue_key:
            recovered = _recover_or_none(config, binding, task_id)
            if recovered:
                issue_key = str(recovered.get("key") or "")
        if issue_key:
            try:
                jira_adapter.request(config, "PUT", f"/rest/api/3/issue/{issue_key}", {"fields": jira_adapter.update_fields(fields)})
                jira_adapter.set_identity(config, binding, issue_key, "task", task_id)
                jira_adapter.sync_status(config, binding, issue_key, task.get("status"))
                task_snapshot = _snapshot(task)
                task_snapshot["start_date"] = jira_adapter.effective_start_date(task)
                task_snapshot["_synced_fields"] = _task_synced_fields(task, binding)
                _upsert_link(binding, "task", task_id, issue_key, parent, task_snapshot)
                db.session.commit()
                result["updated"] += 1
            except Exception as exc:
                db.session.rollback()
                result["failed"] += 1
                result["errors"].append({"entity_type": "task", "jaspen_id": task_id, "error": str(exc)})
        else:
            pending.append((task, fields, parent))

    for offset in range(0, len(pending), 50):
        chunk = pending[offset:offset + 50]
        payload = {"issueUpdates": [{"fields": fields} for _task, fields, _parent in chunk]}
        try:
            data, _ = jira_adapter.request(config, "POST", "/rest/api/3/issue/bulk", payload, timeout=45)
            issues = data.get("issues") if isinstance(data, dict) else []
            issue_errors = data.get("errors") if isinstance(data, dict) else []
            numbered_errors = {}
            for error in issue_errors or []:
                if isinstance(error, dict) and error.get("failedElementNumber") is not None:
                    try:
                        numbered_errors[int(error["failedElementNumber"])] = error
                    except (TypeError, ValueError):
                        pass
            success_index = 0
            for idx, (task, _fields, parent) in enumerate(chunk):
                task_id = str(task["id"])
                error = numbered_errors.get(idx)
                if error is None:
                    issue = issues[success_index] if success_index < len(issues) else None
                    success_index += 1
                else:
                    issue = None
                issue_key = str((issue or {}).get("key") or "")
                if not issue_key:
                    if error is None and not numbered_errors and idx < len(issue_errors):
                        error = issue_errors[idx]
                    error = error or "Jira did not return an issue key."
                    _upsert_link(binding, "task", task_id, snapshot=_snapshot(task), state="failed_create", error=error)
                    result["failed"] += 1
                    result["errors"].append({"entity_type": "task", "jaspen_id": task_id, "error": str(error)})
                    db.session.commit()
                    continue
                try:
                    # Creation succeeded independently of optional Jira
                    # metadata. Save the durable mapping first.
                    initial_snapshot = _snapshot(task)
                    initial_snapshot["start_date"] = jira_adapter.effective_start_date(task)
                    initial_snapshot["_synced_fields"] = _task_synced_fields(task, binding)
                    _upsert_link(binding, "task", task_id, issue_key, parent, initial_snapshot)
                    db.session.commit()
                    jira_adapter.set_identity(config, binding, issue_key, "task", task_id)
                    jira_adapter.sync_status(config, binding, issue_key, task.get("status"))
                    task_snapshot = _created_task_snapshot(config, binding, issue_key, task)
                    _upsert_link(binding, "task", task_id, issue_key, parent, task_snapshot)
                    db.session.commit()
                    result["created"] += 1
                except Exception as exc:
                    db.session.rollback()
                    # The issue exists; persist the key so Retry updates instead of duplicating.
                    task_snapshot = _created_task_snapshot(config, binding, issue_key, task)
                    _upsert_link(binding, "task", task_id, issue_key, parent, task_snapshot, state="active", error=exc)
                    db.session.commit()
                    result["failed"] += 1
                    result["errors"].append({"entity_type": "task", "jaspen_id": task_id, "error": str(exc)})
        except Exception as exc:
            db.session.rollback()
            for task, _fields, _parent in chunk:
                task_id = str(task["id"])
                _upsert_link(binding, "task", task_id, snapshot=_snapshot(task), state="failed_create", error=exc)
                result["failed"] += 1
                result["errors"].append({"entity_type": "task", "jaspen_id": task_id, "error": str(exc)})
            db.session.commit()

    task_links = {
        link.jaspen_id: link.external_id for link in PmSyncLink.query.filter_by(binding_id=binding.id, entity_type="task", state="active").all()
        if link.external_id
    }
    for task in tasks:
        dependent_id = str(task["id"])
        for prerequisite_id in (task.get("depends_on") or []):
            dep_id = f"{prerequisite_id}->{dependent_id}"
            if ("dependency", dep_id) in existing:
                continue
            inward = task_links.get(str(prerequisite_id)); outward = task_links.get(dependent_id)
            if not inward or not outward:
                continue
            try:
                data, _ = jira_adapter.request(config, "POST", "/rest/api/3/issueLink", {
                    "type": {"name": "Blocks"}, "inwardIssue": {"key": inward}, "outwardIssue": {"key": outward},
                })
                external_id = str(data.get("id") or dep_id) if isinstance(data, dict) else dep_id
                _upsert_link(binding, "dependency", dep_id, external_id, snapshot={"from": prerequisite_id, "to": dependent_id})
                db.session.commit()
                result["dependencies"] += 1
            except Exception as exc:
                db.session.rollback()
                result["failed"] += 1
                result["errors"].append({"entity_type": "dependency", "jaspen_id": dep_id, "error": str(exc)})

    binding.last_push_at = _now()
    if result["errors"]:
        binding.status = "partial" if result["created"] or result["updated"] else "error"
        binding.failure_count = int(binding.failure_count or 0) + 1
        binding.next_retry_at = _now() + timedelta(minutes=min(60, 2 ** min(binding.failure_count, 5)))
    else:
        binding.status = "active"
        binding.last_success_at = _now()
        binding.failure_count = 0
        binding.next_retry_at = None
    _record_log(binding, trigger, result)
    db.session.commit()
    result["success"] = not result["errors"]
    result["binding"] = binding.to_dict()
    return result
