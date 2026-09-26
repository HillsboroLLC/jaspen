"""Public share links for scorecards and trade-off comparisons.

Owner endpoints (JWT):   preview, create, list, revoke.
Public endpoints:        view a live link, report a link.
Admin endpoints (JWT):   list/revoke any link, disable sharing for an account.
"""

import hashlib
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request
from flask_jwt_extended import get_jwt_identity, jwt_required
from sqlalchemy import func

from app import db, limiter
from app.admin_audit import append_admin_audit_event
from app.admin_policy import is_global_admin
from app.models import SharedArtifact, SharedArtifactReport, User
from app.sharing import (
    ARTIFACT_TYPES,
    REPORT_REASONS,
    active_link_limit,
    build_snapshot,
    content_summary,
    daily_create_limit,
    expiry_from_days,
    link_is_live,
    new_token,
    parse_expiry_days,
    sharing_block_reason,
    snapshot_size_ok,
)


sharing_bp = Blueprint('sharing', __name__)

UNAVAILABLE = {'error': 'This link is no longer available.', 'code': 'share_unavailable'}
BLOCK_MESSAGES = {
    'user_not_found': 'User not found.',
    'sharing_disabled': 'Sharing has been disabled for this account. Contact support if you think this is a mistake.',
    'paid_plan_required': 'Sharing is available on paid plans, starting with Starter.',
}


def _client_ip():
    # Cloudflare sits in front of production and sets the real visitor address;
    # without it every visitor would share nginx's address and one rate bucket.
    for header in ('CF-Connecting-IP', 'X-Real-IP'):
        value = str(request.headers.get(header) or '').strip()
        if value:
            return value
    forwarded = str(request.headers.get('X-Forwarded-For') or '').split(',')[0].strip()
    return forwarded or request.remote_addr or 'unknown'


def _view_rate_limit():
    return str(current_app.config.get('SHARE_PUBLIC_VIEW_RATE_LIMIT') or '60 per minute')


def _report_rate_limit():
    return str(current_app.config.get('SHARE_REPORT_RATE_LIMIT') or '5 per hour')


def _token_key():
    return f"share-token:{(request.view_args or {}).get('token', '')}"


def _noindex(response, status=200):
    response.status_code = status
    response.headers['X-Robots-Tag'] = 'noindex, nofollow, noarchive'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


def _iso(value):
    return value.isoformat() + 'Z' if value else None


def _share_url(token):
    base = str(current_app.config.get('FRONTEND_BASE_URL') or 'https://jaspen.ai').rstrip('/')
    return f'{base}/s/{token}'


def _link_json(link, *, include_url=True):
    now = datetime.utcnow()
    status = 'active'
    if link.revoked_at is not None:
        status = 'revoked'
    elif link.expires_at is not None and link.expires_at <= now:
        status = 'expired'
    data = {
        'id': link.id,
        'artifact_type': link.artifact_type,
        'thread_id': link.thread_id,
        'source_id': link.source_id,
        'title': link.title,
        'include_evidence': bool(link.include_evidence),
        'created_at': _iso(link.created_at),
        'expires_at': _iso(link.expires_at),
        'revoked_at': _iso(link.revoked_at),
        'revoked_by': link.revoked_by,
        'status': status,
        'view_count': int(link.view_count or 0),
        'last_viewed_at': _iso(link.last_viewed_at),
    }
    if include_url:
        data['url'] = _share_url(link.token)
    return data


def _current_user():
    return User.query.filter_by(id=str(get_jwt_identity())).first()


def _load_thread_cards(user_id, thread_id):
    """Return (session, cards) for a thread the user owns, or (None, None)."""
    from app.routes.sessions import load_user_sessions
    from app.routes.strategy import _load_scenarios, _resolve_session_entry
    from app.scorecards import collect_peer_scorecards

    sessions = load_user_sessions(user_id) or {}
    _key, session = _resolve_session_entry(sessions, thread_id)
    if not isinstance(session, dict):
        return None, None
    thread_data = (_load_scenarios(user_id) or {}).get(thread_id) or {}
    cards = collect_peer_scorecards(
        user_id,
        thread_id,
        legacy_session=session,
        legacy_thread_data=thread_data if isinstance(thread_data, dict) else {},
    )
    return session, cards or []


def _prepare(user, body):
    """Validate a preview/create request and build its sanitized snapshot."""
    artifact_type = str(body.get('artifact_type') or '').strip().lower()
    if artifact_type not in ARTIFACT_TYPES:
        return None, (jsonify({'error': 'artifact_type must be "scorecard" or "tradeoff".'}), 400)
    thread_id = str(body.get('thread_id') or '').strip()
    if not thread_id:
        return None, (jsonify({'error': 'thread_id is required.'}), 400)
    include_evidence = body.get('include_evidence') is True

    session, cards = _load_thread_cards(user.id, thread_id)
    if session is None:
        return None, (jsonify({'error': 'Thread not found.'}), 404)
    try:
        snapshot, title, source_id, evidence_available = build_snapshot(
            artifact_type=artifact_type,
            cards=cards,
            include_evidence=include_evidence,
            scorecard_id=body.get('scorecard_id'),
            thread_name=session.get('name'),
            strategy_objective=session.get('strategy_objective'),
            portfolio_summary=session.get('portfolio_summary'),
        )
    except ValueError as error:
        messages = {
            'scorecard_not_found': ('Scorecard not found in this thread.', 404),
            'not_enough_scorecards': ('A trade-off needs at least two included scorecards.', 400),
        }
        message, status = messages.get(str(error), ('Could not prepare this share.', 400))
        return None, (jsonify({'error': message, 'code': str(error)}), status)
    if not snapshot_size_ok(snapshot):
        return None, (jsonify({'error': 'This artifact is too large to share.', 'code': 'too_large'}), 413)
    return {
        'artifact_type': artifact_type,
        'thread_id': thread_id,
        'source_id': source_id,
        'title': title,
        'snapshot': snapshot,
        'include_evidence': include_evidence,
        'summary': content_summary(
            snapshot, include_evidence=include_evidence, evidence_available=evidence_available,
        ),
    }, None


def _blocked(user):
    reason = sharing_block_reason(user)
    if reason:
        status = 404 if reason == 'user_not_found' else 403
        return jsonify({'error': BLOCK_MESSAGES[reason], 'code': reason}), status
    return None


# ── Owner ────────────────────────────────────────────────────────────────────

@sharing_bp.route('/preview', methods=['POST'])
@jwt_required()
@limiter.limit('60 per minute')
def preview_share():
    user = _current_user()
    blocked = _blocked(user)
    if blocked:
        return blocked
    prepared, error = _prepare(user, request.get_json(silent=True) or {})
    if error:
        return error
    return jsonify({
        'artifact_type': prepared['artifact_type'],
        'title': prepared['title'],
        'include_evidence': prepared['include_evidence'],
        'snapshot': prepared['snapshot'],
        'summary': prepared['summary'],
    })


@sharing_bp.route('', methods=['POST'])
@jwt_required()
@limiter.limit('20 per minute')
def create_share():
    user = _current_user()
    blocked = _blocked(user)
    if blocked:
        return blocked
    body = request.get_json(silent=True) or {}
    days, expiry_error = parse_expiry_days(body.get('expires_in_days'))
    if expiry_error:
        return jsonify({'error': expiry_error, 'code': 'invalid_expiry'}), 400

    now = datetime.utcnow()
    created_today = SharedArtifact.query.filter(
        SharedArtifact.owner_user_id == user.id,
        SharedArtifact.created_at >= now - timedelta(days=1),
    ).count()
    if created_today >= daily_create_limit():
        return jsonify({
            'error': f'You can create up to {daily_create_limit()} share links per day. Try again tomorrow.',
            'code': 'daily_share_limit',
        }), 429
    active = SharedArtifact.query.filter(
        SharedArtifact.owner_user_id == user.id,
        SharedArtifact.revoked_at.is_(None),
        (SharedArtifact.expires_at.is_(None)) | (SharedArtifact.expires_at > now),
    ).count()
    if active >= active_link_limit():
        return jsonify({
            'error': f'You have {active} active share links, the maximum. Turn off a link you no longer need.',
            'code': 'active_share_limit',
        }), 429

    prepared, error = _prepare(user, body)
    if error:
        return error
    link = SharedArtifact(
        token=new_token(),
        owner_user_id=user.id,
        thread_id=prepared['thread_id'],
        artifact_type=prepared['artifact_type'],
        source_id=prepared['source_id'],
        title=prepared['title'],
        snapshot_json=prepared['snapshot'],
        include_evidence=prepared['include_evidence'],
        created_at=now,
        expires_at=expiry_from_days(days, now),
        view_count=0,
    )
    db.session.add(link)
    db.session.commit()
    return jsonify({'link': _link_json(link), 'summary': prepared['summary']}), 201


@sharing_bp.route('', methods=['GET'])
@jwt_required()
def list_shares():
    user = _current_user()
    if not user:
        return jsonify({'error': 'User not found.'}), 404
    query = SharedArtifact.query.filter_by(owner_user_id=user.id)
    thread_id = str(request.args.get('thread_id') or '').strip()
    if thread_id:
        query = query.filter_by(thread_id=thread_id)
    links = query.order_by(SharedArtifact.created_at.desc()).limit(200).all()
    return jsonify({
        'links': [_link_json(link) for link in links],
        'limits': {'daily_create': daily_create_limit(), 'active': active_link_limit()},
        'can_share': sharing_block_reason(user) is None,
        'block_reason': sharing_block_reason(user),
    })


@sharing_bp.route('/<link_id>', methods=['DELETE'])
@jwt_required()
def revoke_share(link_id):
    user = _current_user()
    if not user:
        return jsonify({'error': 'User not found.'}), 404
    link = SharedArtifact.query.filter_by(id=link_id, owner_user_id=user.id).first()
    if not link:
        return jsonify({'error': 'Share link not found.'}), 404
    if link.revoked_at is None:
        link.revoked_at = datetime.utcnow()
        link.revoked_by = 'owner'
        db.session.commit()
    return jsonify({'link': _link_json(link)})


# ── Public ───────────────────────────────────────────────────────────────────

def _live_link(token):
    token = str(token or '').strip()
    if not token or len(token) > 64:
        return None
    link = SharedArtifact.query.filter_by(token=token).first()
    if not link_is_live(link):
        return None
    owner = User.query.filter_by(id=link.owner_user_id).first()
    # A link stops serving while its owner is off a paid plan or blocked.
    if sharing_block_reason(owner) is not None:
        return None
    return link


@sharing_bp.route('/public/<token>', methods=['GET'])
@limiter.limit(_view_rate_limit, key_func=_client_ip)
@limiter.limit('600 per hour', key_func=_token_key)
def view_public_share(token):
    link = _live_link(token)
    if link is None:
        return _noindex(jsonify(UNAVAILABLE), 404)
    SharedArtifact.query.filter_by(id=link.id).update({
        SharedArtifact.view_count: func.coalesce(SharedArtifact.view_count, 0) + 1,
        SharedArtifact.last_viewed_at: datetime.utcnow(),
    }, synchronize_session=False)
    db.session.commit()
    return _noindex(jsonify({
        'artifact_type': link.artifact_type,
        'title': link.title,
        'created_at': _iso(link.created_at),
        'expires_at': _iso(link.expires_at),
        'include_evidence': bool(link.include_evidence),
        'snapshot': link.snapshot_json,
    }))


@sharing_bp.route('/public/<token>/report', methods=['POST'])
@limiter.limit(_report_rate_limit, key_func=_client_ip)
def report_public_share(token):
    link = SharedArtifact.query.filter_by(token=str(token or '').strip()[:64]).first()
    if link is None:
        return _noindex(jsonify(UNAVAILABLE), 404)
    body = request.get_json(silent=True) or {}
    reason = str(body.get('reason') or '').strip().lower()
    if reason not in REPORT_REASONS:
        return _noindex(jsonify({'error': 'Choose a reason for the report.', 'code': 'invalid_reason'}), 400)
    details = str(body.get('details') or '').strip()[:2000] or None
    fingerprint = hashlib.sha256(
        f"{current_app.config.get('SECRET_KEY', '')}:{_client_ip()}".encode('utf-8')
    ).hexdigest()
    db.session.add(SharedArtifactReport(
        shared_artifact_id=link.id,
        reason=reason,
        details=details,
        reporter_fingerprint=fingerprint,
    ))
    db.session.commit()
    current_app.logger.warning('[share-report] link=%s reason=%s', link.id, reason)
    return _noindex(jsonify({'ok': True}), 201)


# ── Admin ────────────────────────────────────────────────────────────────────

def _require_admin():
    user = _current_user()
    if not user:
        return None, (jsonify({'error': 'User not found.'}), 404)
    if not is_global_admin(user, app_config=current_app.config):
        return None, (jsonify({'error': 'Admin access required.'}), 403)
    return user, None


@sharing_bp.route('/admin/links', methods=['GET'])
@jwt_required()
def admin_list_links():
    _admin, error = _require_admin()
    if error:
        return error
    query = SharedArtifact.query
    user_id = str(request.args.get('user_id') or '').strip()
    if user_id:
        query = query.filter_by(owner_user_id=user_id)
    token = str(request.args.get('token') or '').strip()
    if token:
        # Accept a pasted URL as well as a bare token.
        query = query.filter_by(token=token.rstrip('/').rsplit('/', 1)[-1])
    if str(request.args.get('reported') or '').lower() in ('1', 'true', 'yes'):
        query = query.filter(SharedArtifact.id.in_(
            db.session.query(SharedArtifactReport.shared_artifact_id)
        ))
    links = query.order_by(SharedArtifact.created_at.desc()).limit(200).all()
    report_counts = dict(
        db.session.query(SharedArtifactReport.shared_artifact_id, func.count(SharedArtifactReport.id))
        .filter(SharedArtifactReport.shared_artifact_id.in_([link.id for link in links] or ['']))
        .group_by(SharedArtifactReport.shared_artifact_id)
        .all()
    )
    return jsonify({'links': [
        {**_link_json(link), 'owner_user_id': link.owner_user_id, 'report_count': int(report_counts.get(link.id, 0))}
        for link in links
    ]})


@sharing_bp.route('/admin/links/<link_id>/revoke', methods=['POST'])
@jwt_required()
def admin_revoke_link(link_id):
    admin, error = _require_admin()
    if error:
        return error
    link = SharedArtifact.query.filter_by(id=link_id).first()
    if not link:
        return jsonify({'error': 'Share link not found.'}), 404
    reason = str((request.get_json(silent=True) or {}).get('reason') or '').strip()[:255] or None
    if link.revoked_at is None:
        link.revoked_at = datetime.utcnow()
        link.revoked_by = 'admin'
        link.revoked_reason = reason
    append_admin_audit_event(
        actor_user_id=admin.id,
        actor_email=admin.email,
        action='share_link_revoked',
        target_user_id=link.owner_user_id,
        details={'link_id': link.id, 'reason': reason},
    )
    db.session.commit()
    return jsonify({'link': _link_json(link)})


@sharing_bp.route('/admin/users/<user_id>', methods=['GET'])
@jwt_required()
def admin_get_user_sharing(user_id):
    _admin, error = _require_admin()
    if error:
        return error
    target = User.query.filter_by(id=user_id).first()
    if not target:
        return jsonify({'error': 'User not found.'}), 404
    return jsonify({
        'user_id': target.id,
        'sharing_disabled': bool(target.sharing_disabled),
        'block_reason': sharing_block_reason(target),
    })


@sharing_bp.route('/admin/users/<user_id>', methods=['PATCH'])
@jwt_required()
def admin_set_user_sharing(user_id):
    admin, error = _require_admin()
    if error:
        return error
    target = User.query.filter_by(id=user_id).first()
    if not target:
        return jsonify({'error': 'User not found.'}), 404
    body = request.get_json(silent=True) or {}
    if not isinstance(body.get('sharing_disabled'), bool):
        return jsonify({'error': 'sharing_disabled must be true or false.'}), 400
    target.sharing_disabled = body['sharing_disabled']
    append_admin_audit_event(
        actor_user_id=admin.id,
        actor_email=admin.email,
        action='sharing_disabled' if target.sharing_disabled else 'sharing_enabled',
        target_user_id=target.id,
        target_email=target.email,
    )
    db.session.commit()
    return jsonify({'user_id': target.id, 'sharing_disabled': bool(target.sharing_disabled)})
