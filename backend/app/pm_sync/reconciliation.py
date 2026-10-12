"""Provider-neutral three-way reconciliation for execution plans."""
from datetime import datetime, timezone

from app import db
from app.models import ConnectorSyncLog
from app.models_pm_sync import PmSyncLink
from app.pm_sync.provider import get_provider
from app.pm_sync.service import get_plan, push_binding
from app.scenarios_store import load_scenarios_data, save_scenarios_data

FIELDS = ("title", "description", "owner", "owner_email", "status", "start_date", "due_date")


def _iso(value):
    return value.isoformat() if isinstance(value, datetime) else (str(value or "").strip() or None)


def _dt(value):
    try:
        result = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return result if result.tzinfo else result.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _snapshot(task):
    return {key: task.get(key) for key in FIELDS}


def _field_times(task):
    per_field = task.get("field_updated_at") if isinstance(task.get("field_updated_at"), dict) else {}
    return {key: _iso(per_field.get(key)) or _iso(task.get("updated_at")) for key in FIELDS}


def resolve_conflict(policy, local_time=None, remote_time=None):
    if policy == "prefer_jaspen":
        return "local"
    if policy == "prefer_external":
        return "remote"
    if policy == "latest_wins":
        local, remote = _dt(local_time), _dt(remote_time)
        if local and remote and local != remote:
            return "local" if local > remote else "remote"
    return "manual"


def _save_plan(binding, plan):
    data = load_scenarios_data(binding.user_id)
    thread = data.get(binding.thread_id)
    if not isinstance(thread, dict):
        raise LookupError("Thread not found.")
    by_scorecard = thread.get("wbs_by_scorecard") if isinstance(thread.get("wbs_by_scorecard"), dict) else {}
    if binding.plan_key in by_scorecard:
        by_scorecard[binding.plan_key] = plan
        thread["wbs_by_scorecard"] = by_scorecard
    if str(thread.get("active_execution_scorecard_id") or "") == binding.plan_key or not by_scorecard:
        thread["project_wbs"] = plan
    data[binding.thread_id] = thread
    save_scenarios_data(binding.user_id, data)


def _log(binding, trigger, result):
    problems = [*(result["errors"] or []), *(result["conflicts"] or [])]
    synced = result["pulled"] + result["pushed"] + result["created"]
    row = ConnectorSyncLog(
        user_id=binding.user_id, connector_id=binding.connector_id, thread_id=binding.thread_id,
        action="pm_sync", status="success" if not problems else ("partial" if synced else "failed"),
        items_synced=synced,
        error_message=("; ".join(str(item.get("error") or item.get("reason") or "") for item in problems)[:2000] or None),
        sync_metadata={"binding_id": binding.id, "direction": "two_way", "trigger": trigger,
            "counts": {key: result[key] for key in ("created", "pulled", "pushed", "deleted", "failed")},
            "conflicts": result["conflicts"][:50], "unknown_statuses": result["unknown_statuses"][:50],
            "errors": result["errors"][:50]},
    )
    db.session.add(row)


def reconcile_binding(binding, trigger="sync_now"):
    if binding.mode == "push_only":
        return push_binding(binding, trigger=trigger)
    plan, _ = get_plan(binding.user_id, binding.thread_id, binding.plan_key)
    provider = get_provider(binding.connector_id)
    config = provider.assert_connected(binding.user_id, binding.external_container_id)
    tasks = {str(row.get("id")): row for row in (plan.get("tasks") or []) if isinstance(row, dict) and row.get("id")}
    links = PmSyncLink.query.filter_by(binding_id=binding.id, entity_type="task").all()
    result = {"created": 0, "pulled": 0, "pushed": 0, "deleted": 0, "failed": 0,
              "conflicts": [], "unknown_statuses": [], "errors": []}
    changed = False
    for link in links:
        task = tasks.get(link.jaspen_id)
        if not task or not link.external_id:
            continue
        try:
            remote = provider.get_item(config, binding, link.external_id)
            if remote.get("deleted"):
                task["pm_sync_state"] = {"state": "removed_in_jira", "external_id": link.external_id,
                    "detected_at": datetime.utcnow().isoformat()}
                link.state = "removed_external"; result["deleted"] += 1; changed = True
                continue
            if remote.get("status_error"):
                result["unknown_statuses"].append({"task_id": link.jaspen_id, "status": remote["status_error"]})
            base = link.base_snapshot if isinstance(link.base_snapshot, dict) else {}
            local, local_times = _snapshot(task), _field_times(task)
            outside = remote.get("values") if isinstance(remote.get("values"), dict) else {}
            outside_times = remote.get("changed_at") if isinstance(remote.get("changed_at"), dict) else {}
            supported = set(remote.get("supported_fields") or FIELDS)
            outgoing = {}
            task_conflicts = []
            for field in FIELDS:
                if field not in supported or (field == "status" and remote.get("status_error")):
                    continue
                previous, here, there = base.get(field), local.get(field), outside.get(field)
                local_changed, remote_changed = here != previous, there != previous
                if not local_changed and not remote_changed:
                    continue
                if local_changed and not remote_changed:
                    outgoing[field] = here
                    continue
                policy = str((binding.field_policy_overrides or {}).get(field) or binding.conflict_policy or "manual_review")
                winner = "remote" if remote_changed and not local_changed else resolve_conflict(policy, local_times.get(field), outside_times.get(field))
                if winner == "remote":
                    task[field] = there
                    task.setdefault("field_updated_at", {})[field] = outside_times.get(field) or datetime.utcnow().isoformat()
                    result["pulled"] += 1; changed = True
                elif winner == "local":
                    outgoing[field] = here
                else:
                    conflict = {"task_id": link.jaspen_id, "field": field, "jaspen": here, "external": there,
                                "reason": "Both changed and no reliable latest timestamp is available."}
                    result["conflicts"].append(conflict); task_conflicts.append(conflict)
            if outgoing:
                state = provider.update_item(config, binding, link.external_id, outgoing, task)
                if state.get("status_mapped") is False:
                    result["unknown_statuses"].append({"task_id": link.jaspen_id, "status": outgoing.get("status")})
                result["pushed"] += 1
            if not task_conflicts:
                link.base_snapshot = _snapshot(task); link.external_version = _iso(remote.get("version"))
                link.jaspen_version = _iso(task.get("updated_at")); link.last_synced_at = datetime.utcnow()
                link.state = "active"; link.last_error = None
        except Exception as exc:
            db.session.rollback(); result["failed"] += 1
            result["errors"].append({"entity_type": "task", "jaspen_id": link.jaspen_id, "error": str(exc)})
    if changed:
        plan["tasks"] = list(tasks.values())
        _save_plan(binding, plan)
    known = {link.jaspen_id for link in links}
    if any(str(row.get("id")) not in known for row in plan.get("tasks") or []):
        pushed = push_binding(binding, plan, trigger=trigger)
        result["created"] += int(pushed.get("created") or 0)
        result["pushed"] += int(pushed.get("updated") or 0)
        result["failed"] += int(pushed.get("failed") or 0)
        result["errors"].extend(pushed.get("errors") or [])
    now = datetime.utcnow(); binding.last_pull_at = now; binding.last_push_at = now
    binding.status = "partial" if result["conflicts"] else ("error" if result["errors"] else "active")
    if not result["errors"] and not result["conflicts"]:
        binding.last_success_at = now; binding.failure_count = 0; binding.next_retry_at = None
    _log(binding, trigger, result); db.session.commit()
    result["success"] = not result["errors"] and not result["conflicts"]
    result["binding"] = binding.to_dict()
    return result


def list_logs(binding, limit=20):
    rows = ConnectorSyncLog.query.filter_by(user_id=binding.user_id, connector_id=binding.connector_id,
        thread_id=binding.thread_id).order_by(ConnectorSyncLog.created_at.desc()).limit(limit * 3).all()
    return [row.to_dict() for row in rows if (row.sync_metadata or {}).get("binding_id") == binding.id][:limit]
