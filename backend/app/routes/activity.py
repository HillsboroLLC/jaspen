from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import desc

from app.models import ConnectorSyncLog, OrganizationMember, User, UserDataset
from app.orgs import can_manage_org, resolve_active_org_for_user
from app.scenarios_store import load_scenarios_data

from .sessions import load_user_sessions

activity_bp = Blueprint('activity', __name__)

ALLOWED_TYPES = {
    'score_completed',
    'scenario_created',
    'scenario_adopted',
    'wbs_generated',
    'wbs_edited',
    'connector_sync',
    'team_member_joined',
    'data_uploaded',
    'project_activity',
}


def _parse_int(value, default=50, minimum=0, maximum=500):
    try:
        parsed = int(value)
    except Exception:
        parsed = default
    parsed = max(minimum, parsed)
    if maximum is not None:
        parsed = min(maximum, parsed)
    return parsed


def _parse_dt(value):
    if isinstance(value, datetime):
        return value
    text = str(value or '').strip()
    if not text:
        return None
    if text.endswith('Z'):
        text = text[:-1]
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _session_name(session, thread_id):
    if not isinstance(session, dict):
        return f'Thread {thread_id}'
    result = session.get('result') if isinstance(session.get('result'), dict) else {}
    return (
        result.get('project_name')
        or result.get('name')
        or session.get('name')
        or f'Thread {thread_id}'
    )


def _session_score(session):
    if not isinstance(session, dict):
        return None
    result = session.get('result') if isinstance(session.get('result'), dict) else {}
    raw = (
        result.get('jaspen_score')
        or result.get('overall_score')
        or result.get('score')
    )
    try:
        return float(raw)
    except Exception:
        return None


def _append_event(events, *, event_type, description, timestamp, user_id=None, user_name=None, project_name=None, metadata=None):
    if event_type not in ALLOWED_TYPES:
        return
    ts = _parse_dt(timestamp)
    if not ts:
        return
    events.append({
        'type': event_type,
        'description': str(description or '').strip(),
        'project_name': project_name,
        'user_id': user_id,
        'user_name': user_name,
        'timestamp': ts.isoformat(),
        '_sort_ts': ts,
        'metadata': metadata if isinstance(metadata, dict) else {},
    })


def _collect_session_events(events, target_user_id, target_user_name):
    sessions = load_user_sessions(target_user_id) or {}
    if not isinstance(sessions, dict):
        return

    scenarios_data = load_scenarios_data(target_user_id) or {}

    for key, session in sessions.items():
        if not isinstance(session, dict):
            continue

        thread_id = str(session.get('session_id') or key or '').strip()
        if not thread_id:
            continue

        project_name = _session_name(session, thread_id)
        score = _session_score(session)
        status = str(session.get('status') or '').strip().lower()
        session_ts = session.get('timestamp') or session.get('created')

        if status == 'completed' or score is not None:
            descriptor = f"Completed analysis for {project_name}"
            if score is not None:
                descriptor = f"Completed analysis for {project_name} (score {score:.0f})"
            _append_event(
                events,
                event_type='score_completed',
                description=descriptor,
                timestamp=session_ts,
                user_id=target_user_id,
                user_name=target_user_name,
                project_name=project_name,
                metadata={'thread_id': thread_id, 'jaspen_score': score},
            )

        payload = session.get('payload') if isinstance(session.get('payload'), dict) else {}
        feed = payload.get('activity_feed') if isinstance(payload.get('activity_feed'), list) else []
        for item in feed:
            if not isinstance(item, dict):
                continue
            _append_event(
                events,
                event_type='project_activity',
                description=item.get('action') or 'Project activity updated',
                timestamp=item.get('timestamp'),
                user_id=str(item.get('actor_user_id') or target_user_id),
                user_name=item.get('actor_name') or target_user_name,
                project_name=project_name,
                metadata={
                    'thread_id': thread_id,
                    'details': item.get('details') if isinstance(item.get('details'), dict) else {},
                },
            )

        thread_data = scenarios_data.get(thread_id) if isinstance(scenarios_data.get(thread_id), dict) else {}
        scenarios = thread_data.get('scenarios') if isinstance(thread_data.get('scenarios'), dict) else {}
        for scenario in scenarios.values():
            if not isinstance(scenario, dict):
                continue
            _append_event(
                events,
                event_type='scenario_created',
                description=f"Created scenario '{scenario.get('label') or 'Scenario'}'",
                timestamp=scenario.get('created_at') or scenario.get('updated_at') or session_ts,
                user_id=target_user_id,
                user_name=target_user_name,
                project_name=project_name,
                metadata={
                    'thread_id': thread_id,
                    'scenario_id': scenario.get('scenario_id'),
                },
            )

        adopted_id = str(thread_data.get('adopted_scenario_id') or '').strip()
        adopted = scenarios.get(adopted_id) if adopted_id else None
        if isinstance(adopted, dict):
            _append_event(
                events,
                event_type='scenario_adopted',
                description=f"Adopted scenario '{adopted.get('label') or 'Scenario'}'",
                timestamp=adopted.get('updated_at') or adopted.get('created_at') or session_ts,
                user_id=target_user_id,
                user_name=target_user_name,
                project_name=project_name,
                metadata={
                    'thread_id': thread_id,
                    'scenario_id': adopted.get('scenario_id') or adopted_id,
                },
            )

        project_wbs = thread_data.get('project_wbs') if isinstance(thread_data.get('project_wbs'), dict) else {}
        if project_wbs:
            tasks = project_wbs.get('tasks') if isinstance(project_wbs.get('tasks'), list) else []
            _append_event(
                events,
                event_type='wbs_generated',
                description='Generated project WBS',
                timestamp=project_wbs.get('updated_at') or project_wbs.get('created_at') or session_ts,
                user_id=target_user_id,
                user_name=target_user_name,
                project_name=project_name,
                metadata={'thread_id': thread_id, 'task_count': len(tasks)},
            )

            if tasks:
                latest_task_update = None
                for task in tasks:
                    if not isinstance(task, dict):
                        continue
                    dt = _parse_dt(task.get('updated_at') or task.get('created_at'))
                    if dt and (latest_task_update is None or dt > latest_task_update):
                        latest_task_update = dt
                if latest_task_update:
                    _append_event(
                        events,
                        event_type='wbs_edited',
                        description='Edited WBS tasks',
                        timestamp=latest_task_update.isoformat(),
                        user_id=target_user_id,
                        user_name=target_user_name,
                        project_name=project_name,
                        metadata={'thread_id': thread_id, 'task_count': len(tasks)},
                    )


@activity_bp.route('', methods=['GET'])
@jwt_required()
def list_activity():
    requester_id = str(get_jwt_identity() or '').strip()
    requester = User.query.get(requester_id)
    if not requester:
        return jsonify({'error': 'User not found'}), 404

    limit = _parse_int(request.args.get('limit'), default=50, minimum=1, maximum=500)
    offset = _parse_int(request.args.get('offset'), default=0, minimum=0, maximum=5000)
    type_filter = str(request.args.get('type') or '').strip().lower()
    if type_filter and type_filter not in ALLOWED_TYPES:
        return jsonify({'error': f"type must be one of {', '.join(sorted(ALLOWED_TYPES))}"}), 400

    requested_user_id = str(request.args.get('user_id') or '').strip()

    org, membership = resolve_active_org_for_user(requester)
    member_ids = [requester_id]
    if org and membership:
        org_members = OrganizationMember.query.filter_by(organization_id=org.id, status='active').all()
        member_ids = [str(item.user_id) for item in org_members if item.user_id]

    if requested_user_id:
        if requested_user_id not in member_ids:
            return jsonify({'error': 'user_id is not a member of the active organization'}), 400
        if requested_user_id != requester_id and not (membership and can_manage_org(membership.role)):
            return jsonify({'error': 'Only organization owner/admin can filter by another user_id'}), 403
        member_ids = [requested_user_id]

    users = User.query.filter(User.id.in_(member_ids)).all() if member_ids else []
    user_name_by_id = {str(item.id): (item.name or item.email or str(item.id)) for item in users}

    events = []

    for uid in member_ids:
        _collect_session_events(events, uid, user_name_by_id.get(uid, uid))

    datasets = UserDataset.query.filter(UserDataset.user_id.in_(member_ids)).order_by(desc(UserDataset.created_at)).all() if member_ids else []
    for row in datasets:
        _append_event(
            events,
            event_type='data_uploaded',
            description=f"Uploaded dataset '{row.filename}' ({int(row.row_count or 0)} rows)",
            timestamp=row.created_at,
            user_id=str(row.user_id),
            user_name=user_name_by_id.get(str(row.user_id), str(row.user_id)),
            metadata={'dataset_id': row.id, 'row_count': int(row.row_count or 0)},
        )

    sync_logs = (
        ConnectorSyncLog.query
        .filter(ConnectorSyncLog.user_id.in_(member_ids))
        .order_by(desc(ConnectorSyncLog.created_at))
        .limit(1000)
        .all()
        if member_ids else []
    )
    for row in sync_logs:
        descriptor = f"{row.connector_id} {row.action} ({row.status})"
        if row.thread_id:
            descriptor += f" on thread {row.thread_id}"
        _append_event(
            events,
            event_type='connector_sync',
            description=descriptor,
            timestamp=row.created_at,
            user_id=str(row.user_id),
            user_name=user_name_by_id.get(str(row.user_id), str(row.user_id)),
            metadata=row.to_dict(),
        )

    if org:
        joins = (
            OrganizationMember.query
            .filter_by(organization_id=org.id, status='active')
            .order_by(desc(OrganizationMember.joined_at), desc(OrganizationMember.created_at))
            .all()
        )
        for member_row in joins:
            joined_ts = member_row.joined_at or member_row.created_at
            if not joined_ts:
                continue
            member_name = user_name_by_id.get(str(member_row.user_id))
            if not member_name:
                target_user = User.query.get(member_row.user_id)
                member_name = (target_user.name or target_user.email) if target_user else str(member_row.user_id)
            _append_event(
                events,
                event_type='team_member_joined',
                description=f"{member_name} joined the organization as {member_row.role}",
                timestamp=joined_ts,
                user_id=str(member_row.user_id),
                user_name=member_name,
                metadata={'organization_id': org.id, 'role': member_row.role},
            )

    if type_filter:
        events = [item for item in events if item.get('type') == type_filter]

    events.sort(key=lambda item: item.get('_sort_ts') or datetime.min, reverse=True)
    total = len(events)
    sliced = events[offset:offset + limit]

    for row in sliced:
        row.pop('_sort_ts', None)

    return jsonify({
        'events': sliced,
        'total': total,
        'limit': limit,
        'offset': offset,
    }), 200
