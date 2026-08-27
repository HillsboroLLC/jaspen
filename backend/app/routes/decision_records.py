# backend/app/routes/decision_records.py
#
# REST surface for canonical Decision Records. Additive: no existing endpoint
# changes. All routes are owner-scoped; Ring 1 custody means a record is only
# ever visible to the user who owns it (org sharing is a future, consented
# capability — not implemented here by design).

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from .. import db
from ..models import User
from ..models_decision_record import DecisionRecord
from ..decision_records import (
    create_or_refresh_record,
    record_final_decision,
    append_outcome,
    append_lesson,
    set_library_consent,
    set_status,
)

decision_records_bp = Blueprint('decision_records', __name__)


def _current_user():
    user = User.query.get(get_jwt_identity())
    if not user:
        return None
    return user


def _owned_record_or_404(record_id, user):
    record = DecisionRecord.query.filter_by(id=str(record_id), user_id=user.id).first()
    return record


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

    query = DecisionRecord.query.filter_by(user_id=user.id)
    if status:
        query = query.filter_by(status=status)
    if thread_id:
        query = query.filter_by(thread_id=thread_id)
    total = query.count()
    rows = (
        query.order_by(DecisionRecord.updated_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return jsonify({
        'records': [r.to_dict(include_record=False) for r in rows],
        'total': total,
        'limit': limit,
        'offset': offset,
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
    record = _owned_record_or_404(record_id, user)
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
