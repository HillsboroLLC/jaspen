"""Explicit, preview-first sharing of a frozen decision with Jaspen staff."""

import hashlib
import json
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required

from app import db
from app.admin_audit import append_admin_audit_event
from app.admin_policy import is_global_admin
from app.data_sharing import decision_sharing_allowed
from app.models import DecisionShare, Organization, User
from app.orgs import active_membership_for_user, can_manage_org, plan_allows_collaboration
from app.session_access import SessionForbidden, SessionNotFound, resolve_session_for_actor
from app.sharing import (
    ARTIFACT_SCORECARD,
    ARTIFACT_TRADEOFF,
    build_snapshot,
    filter_public_snapshot,
    snapshot_size_ok,
)


decision_shares_bp = Blueprint('decision_shares', __name__)


def _current_user():
    return User.query.filter_by(id=str(get_jwt_identity())).first()


def _iso(value):
    return value.isoformat() + 'Z' if value else None


def _metadata(share, sharer_email=None):
    return {
        'id': share.id,
        'organization_id': share.organization_id,
        'user_id': share.user_id,
        'shared_by': sharer_email,
        'title': share.title,
        'thread_id': share.thread_id,
        'scorecard_id': share.scorecard_id,
        'snapshot_sha256': share.snapshot_sha256,
        'created_at': _iso(share.created_at),
        'withdrawn_at': _iso(share.withdrawn_at),
        'status': 'withdrawn' if share.withdrawn_at else 'shared',
    }


def _hash(snapshot):
    encoded = json.dumps(snapshot, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
    return hashlib.sha256(encoded).hexdigest()


def _prepare(user, body):
    thread_id = str(body.get('thread_id') or '').strip()
    if not thread_id:
        return None, (jsonify({'error': 'thread_id is required.'}), 400)
    try:
        row, membership = resolve_session_for_actor(user, thread_id)
    except SessionNotFound:
        return None, (jsonify({'error': 'Thread not found.'}), 404)
    except SessionForbidden as error:
        return None, (jsonify({'error': str(error)}), 403)

    organization = None
    share_organization_id = None
    if row.organization_id:
        organization = Organization.query.filter_by(id=row.organization_id).first()
        if membership is None:
            return None, (jsonify({'error': 'Thread not found.'}), 404)
        # Every modern account has a solo organization internally. It becomes
        # organization-governed sharing only when its plan can have teammates;
        # individual accounts keep the explicit choice themselves.
        if organization is not None and plan_allows_collaboration(organization.plan_key):
            share_organization_id = organization.id
        if share_organization_id and not decision_sharing_allowed(organization):
            return None, (jsonify({
                'error': 'Sharing decisions with Jaspen is off. An owner or admin can turn it on in Team settings.',
                'code': 'decision_sharing_disabled',
            }), 403)

    from app.scorecards import collect_peer_scorecards

    session = row.payload if isinstance(row.payload, dict) else {}
    thread_data = row.scenarios_json if isinstance(row.scenarios_json, dict) else {}
    cards = collect_peer_scorecards(
        row.user_id,
        thread_id,
        legacy_session=session,
        legacy_thread_data=thread_data,
    ) or []
    scorecard_id = str(body.get('scorecard_id') or '').strip() or None
    artifact_type = ARTIFACT_SCORECARD if scorecard_id else ARTIFACT_TRADEOFF
    try:
        raw_snapshot, title, _source_id, _evidence = build_snapshot(
            artifact_type=artifact_type,
            cards=cards,
            include_evidence=False,
            scorecard_id=scorecard_id,
            thread_name=row.name or session.get('name'),
            strategy_objective=session.get('strategy_objective'),
            portfolio_summary=session.get('portfolio_summary'),
            decision_kit=session.get('decision_kit'),
            data_sources=session.get('report_data_sources'),
        )
    except ValueError as error:
        status = 404 if str(error) == 'scorecard_not_found' else 400
        return None, (jsonify({'error': 'Could not prepare this decision share.', 'code': str(error)}), status)

    # The public-share sanitizer is the single disclosure boundary. Its default
    # settings omit evidence passages, facts, metrics and financial sections.
    snapshot = filter_public_snapshot(raw_snapshot)
    if not snapshot_size_ok(snapshot):
        return None, (jsonify({'error': 'This decision is too large to share.', 'code': 'too_large'}), 413)
    return {
        'title': str(title or '').strip()[:255] or None,
        'row': row,
        'membership': membership,
        'organization': organization,
        'share_organization_id': share_organization_id,
        'thread_id': thread_id,
        'scorecard_id': scorecard_id,
        'artifact_type': artifact_type,
        'snapshot': snapshot,
        'snapshot_sha256': _hash(snapshot),
    }, None


@decision_shares_bp.route('/decision-shares/preview', methods=['POST'])
@jwt_required()
def preview_decision_share():
    user = _current_user()
    if user is None:
        return jsonify({'error': 'User not found.'}), 404
    prepared, error = _prepare(user, request.get_json(silent=True) or {})
    if error:
        return error
    return jsonify({
        'artifact_type': prepared['artifact_type'],
        'snapshot': prepared['snapshot'],
        'snapshot_sha256': prepared['snapshot_sha256'],
    })


@decision_shares_bp.route('/decision-shares', methods=['POST'])
@jwt_required()
def create_decision_share():
    user = _current_user()
    if user is None:
        return jsonify({'error': 'User not found.'}), 404
    body = request.get_json(silent=True) or {}
    if body.get('preview_confirmed') is not True:
        return jsonify({'error': 'Preview confirmation is required.', 'code': 'preview_confirmation_required'}), 400
    prepared, error = _prepare(user, body)
    if error:
        return error
    if str(body.get('snapshot_sha256') or '') != prepared['snapshot_sha256']:
        return jsonify({
            'error': 'This decision changed after the preview. Review the updated preview before sharing.',
            'code': 'preview_changed',
        }), 409
    share = DecisionShare(
        organization_id=prepared['share_organization_id'],
        user_id=user.id,
        thread_id=prepared['thread_id'],
        scorecard_id=prepared['scorecard_id'],
        title=prepared['title'],
        snapshot_json=prepared['snapshot'],
        snapshot_sha256=prepared['snapshot_sha256'],
    )
    db.session.add(share)
    db.session.flush()
    append_admin_audit_event(
        actor_user_id=user.id,
        action='decision_share_create',
        target_user_id=user.id,
        details={'decision_share_id': share.id, 'organization_id': share.organization_id, 'thread_id': share.thread_id},
    )
    return jsonify({'share': _metadata(share, user.email)}), 201


def _with_sharers(shares):
    ids = {share.user_id for share in shares}
    emails = dict(User.query.with_entities(User.id, User.email).filter(User.id.in_(ids)).all()) if ids else {}
    return [_metadata(share, emails.get(share.user_id)) for share in shares]


def _scope_for_user(user):
    org_id = str(user.active_organization_id or '').strip()
    if org_id:
        organization = Organization.query.filter_by(id=org_id).first()
        membership = active_membership_for_user(org_id, str(user.id))
        if membership is not None and organization is not None and plan_allows_collaboration(organization.plan_key):
            query = DecisionShare.query.filter_by(organization_id=org_id)
            if not can_manage_org(membership.role):
                query = query.filter_by(user_id=user.id)
            return query
    return DecisionShare.query.filter_by(organization_id=None, user_id=user.id)


@decision_shares_bp.route('/decision-shares', methods=['GET'])
@jwt_required()
def list_decision_shares():
    user = _current_user()
    if user is None:
        return jsonify({'error': 'User not found.'}), 404
    shares = _scope_for_user(user).order_by(DecisionShare.created_at.desc()).limit(200).all()
    return jsonify({'shares': _with_sharers(shares)})


@decision_shares_bp.route('/decision-shares/<share_id>', methods=['DELETE'])
@jwt_required()
def withdraw_decision_share(share_id):
    user = _current_user()
    if user is None:
        return jsonify({'error': 'User not found.'}), 404
    share = DecisionShare.query.filter_by(id=share_id).first()
    if share is None:
        return jsonify({'error': 'Decision share not found.'}), 404
    allowed = share.user_id == user.id
    if not allowed and share.organization_id:
        membership = active_membership_for_user(share.organization_id, str(user.id))
        allowed = membership is not None and can_manage_org(membership.role)
    if not allowed:
        return jsonify({'error': 'Decision share not found.'}), 404
    if share.withdrawn_at is None:
        share.withdrawn_at = datetime.utcnow()
        share.snapshot_json = None
        share.title = None
        append_admin_audit_event(
            actor_user_id=user.id,
            action='decision_share_withdraw',
            target_user_id=share.user_id,
            details={'decision_share_id': share.id, 'organization_id': share.organization_id, 'thread_id': share.thread_id},
        )
    return jsonify({'share': _metadata(share)})


def _require_admin():
    user = _current_user()
    if user is None or not is_global_admin(user):
        return None, (jsonify({'error': 'Global admin access required.'}), 403)
    return user, None


@decision_shares_bp.route('/admin/decision-shares', methods=['GET'])
@jwt_required()
def admin_list_decision_shares():
    user, error = _require_admin()
    if error:
        return error
    shares = DecisionShare.query.order_by(DecisionShare.created_at.desc()).limit(200).all()
    append_admin_audit_event(
        actor_user_id=user.id,
        action='decision_share_staff_list',
        details={'decision_share_ids': [share.id for share in shares]},
    )
    return jsonify({'shares': _with_sharers(shares)})


@decision_shares_bp.route('/admin/decision-shares/<share_id>', methods=['GET'])
@jwt_required()
def admin_get_decision_share(share_id):
    user, error = _require_admin()
    if error:
        return error
    share = DecisionShare.query.filter_by(id=share_id).first()
    if share is None:
        return jsonify({'error': 'Decision share not found.'}), 404
    append_admin_audit_event(
        actor_user_id=user.id,
        action='decision_share_staff_view',
        target_user_id=share.user_id,
        details={'decision_share_id': share.id, 'organization_id': share.organization_id, 'thread_id': share.thread_id},
    )
    sharer = db.session.get(User, share.user_id)
    return jsonify({**_metadata(share, sharer.email if sharer else None), 'snapshot': share.snapshot_json if share.withdrawn_at is None else None})
