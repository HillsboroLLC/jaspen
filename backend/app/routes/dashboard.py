from datetime import datetime

from flask import Blueprint, current_app, jsonify
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import desc

from app.admin_policy import is_global_admin_email
from app.models import OrganizationMember, User, UserSession
from app.orgs import can_manage_org, normalize_org_role, resolve_active_org_for_user

dashboard_bp = Blueprint("dashboard", __name__)

ALLOWED_PLANS = {"team", "enterprise"}
COLLABORATOR_ROLES = {"collaborator", "viewer"}


def _parse_dt(value):
    if isinstance(value, datetime):
        return value
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1]
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _score_from_row(row):
    payload = row.payload if isinstance(row.payload, dict) else {}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    raw = result.get("jaspen_score") or result.get("overall_score") or result.get("score")
    try:
        return float(raw)
    except Exception:
        return None


def _project_name(row):
    payload = row.payload if isinstance(row.payload, dict) else {}
    result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
    return (
        str(payload.get("name") or "").strip()
        or str(result.get("project_name") or "").strip()
        or str(row.name or "").strip()
        or f"Thread {row.session_id}"
    )


def _project_owner_id(row):
    return str(row.created_by_user_id or row.user_id or "").strip()


def _status_from_row(row):
    payload = row.payload if isinstance(row.payload, dict) else {}
    return str(payload.get("status") or row.status or "in_progress").strip().lower()


def _collect_project_activity(rows, *, user_name_by_id, role_by_user_id, creator_scope_owner_id=None):
    events = []
    collaborator_viewer_events = 0

    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        project_name = _project_name(row)
        project_id = str(row.session_id or "")

        feed = payload.get("activity_feed") if isinstance(payload.get("activity_feed"), list) else []
        for item in feed:
            if not isinstance(item, dict):
                continue
            actor_user_id = str(item.get("actor_user_id") or "").strip()
            actor_role = normalize_org_role(role_by_user_id.get(actor_user_id), default="")
            if creator_scope_owner_id and actor_user_id and actor_user_id != creator_scope_owner_id:
                if actor_role not in COLLABORATOR_ROLES:
                    continue
            if actor_role in COLLABORATOR_ROLES:
                collaborator_viewer_events += 1
            ts = _parse_dt(item.get("timestamp"))
            if not ts:
                continue
            actor_name = str(item.get("actor_name") or "").strip() or user_name_by_id.get(actor_user_id) or "Unknown"
            action = str(item.get("action") or "").strip() or "updated project"
            events.append(
                {
                    "kind": "activity",
                    "project_name": project_name,
                    "project_id": project_id,
                    "actor_user_id": actor_user_id or None,
                    "actor_name": actor_name,
                    "actor_role": actor_role or None,
                    "action": action,
                    "timestamp": ts.isoformat(),
                    "_sort": ts,
                }
            )

        comments = payload.get("comments") if isinstance(payload.get("comments"), list) else []
        for item in comments:
            if not isinstance(item, dict):
                continue
            actor_user_id = str(item.get("author_user_id") or "").strip()
            actor_role = normalize_org_role(role_by_user_id.get(actor_user_id), default="")
            if creator_scope_owner_id and actor_user_id and actor_user_id != creator_scope_owner_id:
                if actor_role not in COLLABORATOR_ROLES:
                    continue
            if actor_role in COLLABORATOR_ROLES:
                collaborator_viewer_events += 1
            ts = _parse_dt(item.get("timestamp"))
            if not ts:
                continue
            actor_name = str(item.get("author_name") or "").strip() or user_name_by_id.get(actor_user_id) or "Unknown"
            events.append(
                {
                    "kind": "comment",
                    "project_name": project_name,
                    "project_id": project_id,
                    "actor_user_id": actor_user_id or None,
                    "actor_name": actor_name,
                    "actor_role": actor_role or None,
                    "action": "added a comment",
                    "timestamp": ts.isoformat(),
                    "_sort": ts,
                }
            )

    events.sort(key=lambda item: item["_sort"], reverse=True)
    return events[:50], collaborator_viewer_events


def _safe_project_label(name, max_len=22):
    label = str(name or "").strip() or "Untitled"
    return label if len(label) <= max_len else f"{label[:max_len - 1]}…"


def _build_score_trend_chart(projects):
    scored = [item for item in projects if item.get("jaspen_score") is not None]
    recent = scored[:8]
    return {
        "type": "line",
        "title": "Recent Project Scores",
        "data": {
            "labels": [_safe_project_label(item.get("project_name")) for item in recent],
            "values": [round(float(item.get("jaspen_score")), 2) for item in recent],
        },
    }


def _build_status_mix_chart(counts):
    return {
        "type": "pie",
        "title": "Project Status Mix",
        "data": {
            "labels": ["Active", "Completed", "Archived"],
            "values": [
                int(counts.get("active") or 0),
                int(counts.get("completed") or 0),
                int(counts.get("archived") or 0),
            ],
        },
    }


def _build_activity_volume_chart(events):
    buckets = {}
    for event in events or []:
        dt = _parse_dt(event.get("timestamp"))
        if not dt:
            continue
        key = dt.date().isoformat()
        buckets[key] = int(buckets.get(key) or 0) + 1

    ordered_days = sorted(buckets.keys(), reverse=True)[:7]
    ordered_days.reverse()
    labels = []
    values = []
    for day in ordered_days:
        try:
            labels.append(datetime.fromisoformat(day).strftime("%b %d"))
        except Exception:
            labels.append(day)
        values.append(int(buckets.get(day) or 0))

    return {
        "type": "bar",
        "title": "Team Activity (7 days)",
        "data": {
            "labels": labels,
            "values": values,
        },
    }


def _latest_insight_cards(rows, *, user_name_by_id):
    cards = []
    for row in rows:
        payload = row.payload if isinstance(row.payload, dict) else {}
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        insight_list = result.get("ai_insights")
        if not isinstance(insight_list, list):
            insight_list = payload.get("ai_insights")
        if not isinstance(insight_list, list):
            continue

        project_name = _project_name(row)
        owner_id = _project_owner_id(row)
        owner_name = user_name_by_id.get(owner_id, "Unknown")
        for insight in insight_list:
            if not isinstance(insight, dict):
                continue
            timestamp = _parse_dt(insight.get("timestamp"))
            cards.append(
                {
                    "id": str(insight.get("id") or f"insight_{row.session_id}_{len(cards)}"),
                    "thread_id": str(row.session_id),
                    "project_name": project_name,
                    "owner_name": owner_name,
                    "summary": str(
                        insight.get("summary")
                        or (insight.get("insight") or {}).get("insight_text")
                        or "Insight captured."
                    ).strip(),
                    "file_name": str(insight.get("file_name") or (insight.get("insight") or {}).get("file_name") or "").strip() or None,
                    "timestamp": timestamp.isoformat() if timestamp else None,
                    "_sort": timestamp or row.updated_at or row.created_at or datetime.min,
                }
            )

    cards.sort(key=lambda item: item["_sort"], reverse=True)
    trimmed = []
    for item in cards[:6]:
        cloned = dict(item)
        cloned.pop("_sort", None)
        trimmed.append(cloned)
    return trimmed


@dashboard_bp.route("/api/dashboard", methods=["GET"])
@jwt_required()
def get_dashboard_data():
    user_id = str(get_jwt_identity() or "").strip()
    user = User.query.get(user_id) if user_id else None
    if not user:
        return jsonify({"error": "User not found"}), 404

    org, membership = resolve_active_org_for_user(user)
    if not org or not membership:
        return jsonify({"error": "No active organization"}), 404

    plan_key = str(org.plan_key or "").strip().lower()
    global_admin = is_global_admin_email(user.email, current_app.config)
    if plan_key not in ALLOWED_PLANS and not global_admin:
        return jsonify({"error": "Dashboard is available on Team and Enterprise plans."}), 403

    membership_role = normalize_org_role(membership.role)
    manager_scope = global_admin or can_manage_org(membership_role)

    members = (
        OrganizationMember.query
        .filter_by(organization_id=org.id, status="active")
        .all()
    )
    role_by_user_id = {str(item.user_id): normalize_org_role(item.role) for item in members if item.user_id}
    member_user_ids = [str(item.user_id) for item in members if item.user_id]

    users = User.query.filter(User.id.in_(member_user_ids)).all() if member_user_ids else []
    user_name_by_id = {
        str(item.id): (str(item.name or "").strip() or str(item.email or "").strip() or str(item.id))
        for item in users
    }

    org_rows = (
        UserSession.query
        .filter(UserSession.organization_id == org.id)
        .order_by(desc(UserSession.updated_at), desc(UserSession.id))
        .limit(1200)
        .all()
    )

    if manager_scope:
        visible_rows = org_rows
        scope = "organization"
    else:
        owner_id = str(user.id)
        visible_rows = [
            row for row in org_rows
            if _project_owner_id(row) == owner_id
        ]
        scope = "creator"

    projects = []
    scored = []
    counts = {"active": 0, "completed": 0, "archived": 0}
    for row in visible_rows:
        status = _status_from_row(row)
        score = _score_from_row(row)
        owner_id = _project_owner_id(row)
        owner_role = normalize_org_role(role_by_user_id.get(owner_id), default="")
        updated = row.updated_at.isoformat() if row.updated_at else None

        if status == "archived":
            counts["archived"] += 1
        elif status == "completed" or score is not None:
            counts["completed"] += 1
        else:
            counts["active"] += 1
        if score is not None:
            scored.append(score)

        projects.append(
            {
                "thread_id": str(row.session_id),
                "project_name": _project_name(row),
                "status": status,
                "jaspen_score": round(score, 2) if score is not None else None,
                "owner_user_id": owner_id or None,
                "owner_name": user_name_by_id.get(owner_id, "Unknown"),
                "owner_role": owner_role or None,
                "updated_at": updated,
                "created_at": row.created_at.isoformat() if row.created_at else None,
            }
        )

    projects.sort(key=lambda item: item.get("updated_at") or "", reverse=True)
    project_rows_for_activity = visible_rows if manager_scope else visible_rows
    activities, collaborator_viewer_events = _collect_project_activity(
        project_rows_for_activity,
        user_name_by_id=user_name_by_id,
        role_by_user_id=role_by_user_id,
        creator_scope_owner_id=None if manager_scope else str(user.id),
    )

    insight_cards = _latest_insight_cards(visible_rows, user_name_by_id=user_name_by_id)
    insight_charts = [
        _build_score_trend_chart(projects),
        _build_status_mix_chart(counts),
        _build_activity_volume_chart(activities),
    ]
    insight_charts = [
        chart for chart in insight_charts
        if isinstance(chart, dict)
        and isinstance(chart.get("data"), dict)
        and isinstance(chart["data"].get("labels"), list)
        and isinstance(chart["data"].get("values"), list)
        and len(chart["data"]["labels"]) > 0
        and len(chart["data"]["values"]) > 0
    ]

    return jsonify(
        {
            "organization": {
                "id": org.id,
                "name": org.name,
                "plan_key": plan_key,
            },
            "membership": {
                "role": membership_role,
                "can_manage": bool(manager_scope),
            },
            "scope": scope,
            "metrics": {
                "projects_total": len(projects),
                "projects_active": counts["active"],
                "projects_completed": counts["completed"],
                "projects_archived": counts["archived"],
                "scored_projects": len(scored),
                "avg_score": round(sum(scored) / len(scored), 1) if scored else None,
                "team_members": len(members),
                "collaborator_viewer_activity": collaborator_viewer_events,
            },
            "projects": projects[:40],
            "activity": activities[:40],
            "insights_widget": {
                "charts": insight_charts,
                "cards": insight_cards,
            },
        }
    ), 200
