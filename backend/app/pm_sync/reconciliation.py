"""Provider-neutral three-way reconciliation for execution plans."""
from datetime import datetime, timezone

from sqlalchemy.exc import SQLAlchemyError

from app import db
from app.models import ConnectorSyncLog
from app.models_pm_sync import PmSyncLink
from app.pm_sync.provider import get_provider
from app.pm_sync import jira_adapter
from app.pm_sync.service import (
    _consume_binding_note, _sync_phases, ensure_start_date_field,
    ensure_task_parent, get_plan, push_binding,
)
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


def _normalized(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (list, tuple)):
        values = [_normalized(item) for item in value]
        values = [item for item in values if item is not None]
        return values or None
    return value


def _snapshot(task, binding=None):
    result = {key: _normalized(task.get(key)) for key in FIELDS}
    if binding is not None and binding.connector_id == "jira_sync" and jira_adapter.owner_is_unassigned(
        result.get("owner"), result.get("owner_email")
    ):
        result["owner"] = None
        result["owner_email"] = None
    if binding is not None and binding.connector_id == "jira_sync" and (binding.config or {}).get("start_date_field_id"):
        from app.pm_sync.jira_adapter import effective_start_date
        result["start_date"] = effective_start_date(task)
    return result


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
    notes = _consume_binding_note(binding, result)
    row = ConnectorSyncLog(
        user_id=binding.user_id, connector_id=binding.connector_id, thread_id=binding.thread_id,
        action="pm_sync", status="success" if not problems else ("partial" if synced else "failed"),
        items_synced=synced,
        error_message=("; ".join(str(item.get("error") or item.get("reason") or "") for item in problems)[:2000] or None),
        sync_metadata={"binding_id": binding.id, "direction": "two_way", "trigger": trigger,
            "counts": {key: result[key] for key in ("created", "pulled", "pushed", "deleted", "failed")},
            "conflicts": result["conflicts"][:50], "unknown_statuses": result["unknown_statuses"][:50],
            "errors": result["errors"][:50], "notes": notes},
    )
    db.session.add(row)


def reconcile_binding(binding, trigger="sync_now"):
    from app.pm_sync.access import enforce_binding_owner, mark_binding

    enforce_binding_owner(binding)
    if binding.mode == "push_only":
        return push_binding(binding, trigger=trigger)
    plan, _ = get_plan(binding.user_id, binding.thread_id, binding.plan_key)
    provider = get_provider(binding.connector_id)
    config = provider.assert_connected(binding.user_id, binding.external_container_id)
    ensure_start_date_field(binding, config)
    tasks = {str(row.get("id")): row for row in (plan.get("tasks") or []) if isinstance(row, dict) and row.get("id")}
    all_links = PmSyncLink.query.filter_by(binding_id=binding.id).all()
    phase_result = {"created": 0, "updated": 0, "failed": 0, "errors": []}
    task_parents = _sync_phases(
        binding, plan, config, {(link.entity_type, link.jaspen_id): link for link in all_links}, phase_result,
    )
    linked_parent_ids = {
        *task_parents.values(),
        *(link.external_id for link in all_links
          if link.entity_type == "phase" and link.state == "active" and link.external_id),
    }
    links = [link for link in all_links if link.entity_type == "task"]
    missing_external_ids = set()
    find_missing = getattr(provider, "find_missing_items", None)
    if callable(find_missing):
        try:
            missing_external_ids = set(find_missing(
                config, binding, {link.external_id for link in links if link.external_id}
            ))
        except Exception:
            # Preserve the established per-issue path if Jira search itself is
            # unavailable; its requests still classify missing and auth errors.
            missing_external_ids = set()
    result = {"created": 0, "pulled": 0, "pushed": 0, "deleted": 0, "failed": 0,
              "conflicts": [], "unknown_statuses": [], "errors": []}
    result["created"] += phase_result["created"]
    result["pushed"] += phase_result["updated"]
    result["failed"] += phase_result["failed"]
    result["errors"].extend(phase_result["errors"])
    changed = False
    for link in links:
        task = tasks.get(link.jaspen_id)
        if not link.external_id:
            continue
        if link.external_id in missing_external_ids:
            link.state = "missing_external"; link.last_error = None
            link.last_synced_at = datetime.utcnow(); result["deleted"] += 1
            if task:
                task["pm_sync_state"] = {"state": "removed_in_jira", "external_id": link.external_id,
                    "detected_at": datetime.utcnow().isoformat()}
                changed = True
            continue
        if not task:
            continue
        try:
            provider.ensure_recovery_identity(config, binding, link.external_id, link.jaspen_id)
            if link.last_error:
                provider.set_identity(config, binding, link.external_id, "task", link.jaspen_id)
                link.last_error = None
            remote = provider.get_item(config, binding, link.external_id)
            if remote.get("deleted"):
                task["pm_sync_state"] = {"state": "removed_in_jira", "external_id": link.external_id,
                    "detected_at": datetime.utcnow().isoformat()}
                link.state = "missing_external"; link.last_error = None
                result["deleted"] += 1; changed = True
                continue
            if remote.get("status_error"):
                result["unknown_statuses"].append({"task_id": link.jaspen_id, "status": remote["status_error"]})
            expected_parent = task_parents.get(link.jaspen_id)
            parent_repaired, effective_parent = ensure_task_parent(
                config, binding, link.external_id, expected_parent,
                current_parent=remote.get("parent_id"), linked_parent_ids=linked_parent_ids,
            )
            if parent_repaired:
                result["pushed"] += 1
            if effective_parent:
                link.external_parent_id = effective_parent
            base = link.base_snapshot if isinstance(link.base_snapshot, dict) else {}
            if "_synced_fields" in base:
                synced_fields = set(base.get("_synced_fields") or [])
            else:
                # Legacy snapshots predate field-delivery tracking. All old
                # fields were supported except start_date, which may only just
                # have become available after discovery.
                synced_fields = set(FIELDS) - {"start_date"}
            preserve_local_empty = set(base.get("_preserve_local_empty_fields") or [])
            local, local_times = _snapshot(task, binding), _field_times(task)
            outside = remote.get("values") if isinstance(remote.get("values"), dict) else {}
            outside_times = remote.get("changed_at") if isinstance(remote.get("changed_at"), dict) else {}
            supported = set(remote.get("supported_fields") or FIELDS)
            outgoing = {}
            task_conflicts = []
            # Ownership is intentionally not generic text reconciliation. A
            # Jira default at creation is provider state, not a human edit.
            # Jaspen sends only mapped owners and accepts only a later,
            # attributable Jira assignee change.
            local_owner = (local.get("owner"), local.get("owner_email"))
            prior_local_owner = (
                _normalized(base.get("_jaspen_owner")),
                _normalized(base.get("_jaspen_owner_email")),
            ) if "_jaspen_owner" in base or "_jaspen_owner_email" in base else local_owner
            remote_owner = (_normalized(outside.get("owner")), _normalized(outside.get("owner_email")))
            owner_change = remote.get("owner_change") if isinstance(remote.get("owner_change"), dict) else {}
            owner_changed_at = _dt(owner_change.get("changed_at"))
            issue_created_at = _dt(remote.get("created_at"))
            last_synced_at = _dt(link.last_synced_at)
            explicit_remote_owner = bool(
                owner_change.get("changed_by_account_id")
                and owner_change.get("changed_by_account_type") in {"atlassian", "customer"}
                and owner_change.get("account_id")
                and owner_change.get("display_name")
                and owner_change.get("account_type") in {"atlassian", "customer"}
                and owner_changed_at
                and (not issue_created_at or owner_changed_at > issue_created_at)
                and (not last_synced_at or owner_changed_at > last_synced_at)
            )
            owner_pushed = False
            if explicit_remote_owner:
                resolved_remote_owner = (
                    _normalized(owner_change.get("display_name")),
                    _normalized(owner_change.get("email")),
                )
                if local_owner != resolved_remote_owner:
                    task["owner"], task["owner_email"] = resolved_remote_owner
                    stamp = owner_change.get("changed_at") or datetime.utcnow().isoformat()
                    task.setdefault("field_updated_at", {})["owner"] = stamp
                    task.setdefault("field_updated_at", {})["owner_email"] = stamp
                    local["owner"], local["owner_email"] = resolved_remote_owner
                    local_owner = resolved_remote_owner
                    result["pulled"] += 1
                    changed = True
            elif local_owner != prior_local_owner and jira_adapter.mapped_owner_account_id(
                binding, local_owner[0], local_owner[1]
            ):
                outgoing["owner"], outgoing["owner_email"] = local_owner
                owner_pushed = True

            for field in (field for field in FIELDS if field not in {"owner", "owner_email"}):
                if field not in supported or (field == "status" and remote.get("status_error")):
                    continue
                previous, here, there = _normalized(base.get(field)), local.get(field), _normalized(outside.get(field))
                if field not in synced_fields:
                    # Jira never received this field. The first supported sync
                    # establishes Jaspen as source instead of treating Jira's
                    # empty placeholder as a user-authored deletion.
                    if here is not None:
                        outgoing[field] = here
                    synced_fields.add(field)
                    continue
                local_changed, remote_changed = here != previous, there != previous
                if field in preserve_local_empty and here is None:
                    # A Jira project default applied during issue creation is
                    # an accepted baseline divergence, not a later Jaspen edit.
                    local_changed = False
                if not local_changed and not remote_changed:
                    continue
                if local_changed and not remote_changed:
                    outgoing[field] = here
                    continue
                if there is None and here is not None and remote_changed:
                    remote_changed_at = _dt(outside_times.get(field))
                    last_synced_at = _dt(link.last_synced_at)
                    if not remote_changed_at or (last_synced_at and remote_changed_at <= last_synced_at):
                        conflict = {
                            "task_id": link.jaspen_id, "field": field, "jaspen": here, "external": there,
                            "reason": "Jira returned an empty value without a verified post-sync clear; Jaspen value preserved.",
                        }
                        result["conflicts"].append(conflict); task_conflicts.append(conflict)
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
                next_base = _snapshot(task, binding)
                next_base["_jaspen_owner"] = local_owner[0]
                next_base["_jaspen_owner_email"] = local_owner[1]
                if explicit_remote_owner or owner_pushed:
                    next_base["owner"], next_base["owner_email"] = local_owner
                    synced_fields.update({"owner", "owner_email"})
                else:
                    # Retain Jira's actual provider-side default separately
                    # from the Jaspen owner that remains authoritative.
                    next_base["owner"], next_base["owner_email"] = remote_owner
                    synced_fields.discard("owner")
                    synced_fields.discard("owner_email")
                still_preserved = []
                for field in preserve_local_empty:
                    if local.get(field) is None and _normalized(outside.get(field)) == _normalized(base.get(field)):
                        next_base[field] = _normalized(base.get(field))
                        still_preserved.append(field)
                if still_preserved:
                    next_base["_preserve_local_empty_fields"] = sorted(still_preserved)
                next_base["_synced_fields"] = sorted(synced_fields)
                link.base_snapshot = next_base; link.external_version = _iso(remote.get("version"))
                link.jaspen_version = _iso(task.get("updated_at")); link.last_synced_at = datetime.utcnow()
                link.state = "active"; link.last_error = None
        except Exception as exc:
            # Roll back only a failed database write. Rolling back for a remote
            # error would discard what earlier links recorded in this pass,
            # such as issues already marked missing.
            if isinstance(exc, SQLAlchemyError):
                db.session.rollback()
            if binding.connector_id == "jira_sync" and jira_adapter.is_missing_issue_error(exc):
                link.state = "missing_external"; link.last_error = None
                link.last_synced_at = datetime.utcnow()
                task["pm_sync_state"] = {"state": "removed_in_jira", "external_id": link.external_id,
                    "detected_at": datetime.utcnow().isoformat()}
                result["deleted"] += 1; changed = True
                continue
            result["failed"] += 1
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
    missing_count = PmSyncLink.query.filter_by(
        binding_id=binding.id, entity_type="task", state="missing_external"
    ).filter(PmSyncLink.external_id.isnot(None)).with_entities(PmSyncLink.external_id).distinct().count()
    config = dict(binding.config or {})
    if missing_count:
        config["missing_issue_count"] = missing_count
    else:
        config.pop("missing_issue_count", None)
    binding.config = config
    now = datetime.utcnow(); binding.last_pull_at = now; binding.last_push_at = now
    binding.status = "partial" if result["conflicts"] else ("error" if result["errors"] else ("links_missing" if missing_count else "active"))
    if result["errors"]:
        mark_binding(binding, status=binding.status, warning_code="sync_failed")
    elif result["conflicts"]:
        mark_binding(binding, status=binding.status, warning_code="sync_conflict")
    elif missing_count:
        mark_binding(binding, status="links_missing", warning_code="links_missing")
    else:
        mark_binding(binding, status="active")
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
