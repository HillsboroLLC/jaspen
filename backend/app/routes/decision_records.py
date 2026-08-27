# backend/app/routes/decision_records.py
#
# REST surface for canonical Decision Records.
#
# Access is ORGANIZATION-scoped (Phase 4). Ring 1 custody means a record never
# leaves the customer, but "the customer" is the organization that owns the
# work, not the individual who happened to author it -- Constitution Art. 26:
# private records become part of THAT CUSTOMER'S organizational memory. Within
# the organization a record inherits the visibility of the project it was
# derived from, so record access and project access can never disagree.

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from .. import db
from ..models import User
from ..models_decision_record import DecisionRecord
from ..decision_records import (
    can_read_record,
    create_or_refresh_record,
    record_final_decision,
    append_outcome,
    append_lesson,
    set_library_consent,
    set_status,
)
from ..decision_retrieval import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    authorized_candidates,
    rank,
    search,
    summarize,
)
from ..session_access import can_write_session, canonical_row

decision_records_bp = Blueprint('decision_records', __name__)


def _current_user():
    user = User.query.get(get_jwt_identity())
    if not user:
        return None
    return user


def _owned_record_or_404(record_id, user):
    """The record, if this user may read it.

    PHASE 4: this used to filter on `user_id`, which made attribution act as
    ownership -- so once Phase 3 gave a team ONE canonical record, every member
    except its creator was locked out of their own organization's decision.
    Access now follows the project the record was derived from, via
    can_read_record(), which is an adapter over the same session chokepoint
    rather than a second authorization system.

    Returns None for both "does not exist" and "not yours", so callers answer
    404 either way and record ids cannot be probed.
    """
    record = DecisionRecord.query.filter_by(id=str(record_id)).first()
    if record is None or not can_read_record(record, user):
        return None
    return record


def _writable_record_or_none(record_id, user):
    """A record this user may MUTATE (human decision, status, tags).

    Read access is not write access: a viewer can see the organization's
    decisions without editing them. Mirrors can_write_session() on the project.
    """
    record = _owned_record_or_404(record_id, user)
    if record is None:
        return None, 404
    row = canonical_row(user, record.thread_id, include_archived=True)
    if row is not None and not can_write_session(row, user):
        return None, 403
    return record, None


@decision_records_bp.route('/from-thread/<thread_id>', methods=['POST'])
@jwt_required()
def create_from_thread(thread_id):
    """Create (or refresh) the Decision Record for a conversation thread.

    Idempotent per thread: repeated calls re-derive the analysis fields and
    never touch human-owned fields (final decision, outcomes, lessons, consent).
    """
    user = _current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    try:
        record, created = create_or_refresh_record(user, thread_id)
    except LookupError as exc:
        return jsonify({'error': str(exc)}), 404
    return jsonify({'record': record.to_dict(), 'created': created}), 201 if created else 200


@decision_records_bp.route('', methods=['GET'])
@decision_records_bp.route('/', methods=['GET'])
@jwt_required()
def list_records():
    user = _current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    status = str(request.args.get('status') or '').strip().lower() or None
    thread_id = str(request.args.get('thread_id') or '').strip() or None
    limit = min(max(int(request.args.get('limit', 50) or 50), 1), 200)
    offset = max(int(request.args.get('offset', 0) or 0), 0)

    # Organization-scoped and permission-filtered, via the same candidate
    # assembly the search endpoint uses. Was filter_by(user_id=user.id).
    rows = authorized_candidates(
        user, status=status, thread_id=thread_id,
    )
    total = len(rows)
    page = rows[offset:offset + limit]

    return jsonify({
        'records': [r.to_dict(include_record=False) for r in page],
        'total': total,
        'limit': limit,
        'offset': offset,
    })


@decision_records_bp.route('/search', methods=['GET'])
@jwt_required()
def search_records():
    """Permission-aware organizational decision retrieval.

    authorized candidates -> ranking -> compact summaries. Returns a BOUNDED
    ranked set of summaries, each carrying the id needed to fetch the full
    canonical record separately. Nothing here assembles long-form payloads or
    conversation history.
    """
    user = _current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404

    query = str(request.args.get('q') or '').strip() or None
    limit = min(max(int(request.args.get('limit', DEFAULT_LIMIT) or DEFAULT_LIMIT), 1), MAX_LIMIT)

    human_decision = request.args.get('human_decision')
    if human_decision is not None:
        human_decision = str(human_decision).strip().lower() in ('1', 'true', 'yes')

    results = search(
        user,
        query,
        limit=limit,
        organization_id=str(request.args.get('organization_id') or '').strip() or None,
        status=str(request.args.get('status') or '').strip().lower() or None,
        thread_id=str(request.args.get('thread_id') or '').strip() or None,
        decision_type=str(request.args.get('decision_type') or '').strip() or None,
        human_decision=human_decision,
    )
    return jsonify({
        'results': results,
        'count': len(results),
        'limit': limit,
        'query': query,
        # Explicit so a future second source (benchmarking signal, personal
        # memory) can be added without silently conflating it with this one.
        'source_types': ['decision_record'],
    })


@decision_records_bp.route('/<record_id>', methods=['GET'])
@jwt_required()
def get_record(record_id):
    user = _current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    record = _owned_record_or_404(record_id, user)
    if not record:
        return jsonify({'error': 'Decision record not found'}), 404
    return jsonify({'record': record.to_dict()})


@decision_records_bp.route('/<record_id>', methods=['PATCH'])
@jwt_required()
def update_record(record_id):
    """Update human-owned fields: final_decision, status, title, tags."""
    user = _current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    record, denied = _writable_record_or_none(record_id, user)
    if denied == 403:
        return jsonify({'error': 'Your role on this project is read-only',
                        'code': 'forbidden'}), 403
    if not record:
        return jsonify({'error': 'Decision record not found'}), 404
    data = request.get_json(silent=True) or {}

    try:
        if 'final_decision' in data:
            # The human decision signal. Capture WHO decided, so the record can
            # show that a person made this call rather than a model.
            record_final_decision(
                record, data.get('final_decision'), decided_by_user_id=user.id
            )
        if 'status' in data:
            set_status(record, data.get('status'))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400

    if isinstance(data.get('title'), str) and data['title'].strip():
        record.title = data['title'].strip()[:255]
    if isinstance(data.get('tags'), list):
        record.tags = [str(t)[:64] for t in data['tags'][:24]]
    if isinstance(data.get('decision_type'), str):
        record.decision_type = data['decision_type'].strip()[:64] or None
    if isinstance(data.get('altitude'), str):
        record.altitude = data['altitude'].strip()[:32] or None
    db.session.commit()
    return jsonify({'record': record.to_dict()})


@decision_records_bp.route('/<record_id>/outcomes', methods=['POST'])
@jwt_required()
def add_outcome(record_id):
    user = _current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    record = _owned_record_or_404(record_id, user)
    if not record:
        return jsonify({'error': 'Decision record not found'}), 404
    data = request.get_json(silent=True) or {}
    summary = str(data.get('summary') or '').strip()
    if not summary:
        return jsonify({'error': 'summary is required'}), 400
    append_outcome(record, summary, extra=data)
    return jsonify({'record': record.to_dict()}), 201


@decision_records_bp.route('/<record_id>/lessons', methods=['POST'])
@jwt_required()
def add_lesson(record_id):
    user = _current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    record = _owned_record_or_404(record_id, user)
    if not record:
        return jsonify({'error': 'Decision record not found'}), 404
    data = request.get_json(silent=True) or {}
    lesson = str(data.get('lesson') or '').strip()
    if not lesson:
        return jsonify({'error': 'lesson is required'}), 400
    append_lesson(record, lesson)
    return jsonify({'record': record.to_dict()}), 201


@decision_records_bp.route('/<record_id>/consent', methods=['POST'])
@jwt_required()
def update_consent(record_id):
    """Ring 2 custody: explicit, revocable Library consent (Art. 21)."""
    user = _current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    record = _owned_record_or_404(record_id, user)
    if not record:
        return jsonify({'error': 'Decision record not found'}), 404
    data = request.get_json(silent=True) or {}
    try:
        set_library_consent(record, data.get('library_consent'))
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    return jsonify({'record': record.to_dict()})
