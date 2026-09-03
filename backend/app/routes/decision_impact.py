# backend/app/routes/decision_impact.py
#
# REST surface for the intake baseline and the Decision Impact Report
# (docs/DECISION_IMPACT_REPORT_SPEC.md). Additive: no existing endpoint changes.
#
# Owner-scoped throughout. The raw submission is Ring 1 customer material and
# is only ever returned to the user who supplied it (spec §3.7, Custody).

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required, get_jwt_identity

from ..models import User
from ..models_decision_baseline import SEALED_BY_ANALYSIS, SEALED_BY_USER, SealedBaselineError
from ..decision_impact import (
    analysis_has_started,
    build_impact_report,
    capture_or_update_draft,
    get_baseline,
    seal_baseline,
)

decision_impact_bp = Blueprint('decision_impact', __name__)


def _current_user():
    return User.query.get(get_jwt_identity())


def _clean_structure(raw):
    """Accept only the shape the correction window collects.

    Whitelisted rather than stored as sent: this payload becomes part of a
    sealed, immutable record, so an unrecognised key would be frozen forever
    with nothing able to read it.
    """
    if not isinstance(raw, dict):
        return None

    def _strings(key):
        values = raw.get(key)
        return [
            str(value).strip()
            for value in (values if isinstance(values, list) else [])
            if str(value or '').strip()
        ]

    criteria = []
    for index, item in enumerate(raw.get('criteria') if isinstance(raw.get('criteria'), list) else []):
        if not isinstance(item, dict):
            continue
        label = str(item.get('label') or '').strip()
        if not label:
            continue
        weight = item.get('weight')
        try:
            weight = float(weight) if weight is not None else None
        except (TypeError, ValueError):
            weight = None
        criteria.append({
            # Identity is a stable key, never the label: renaming a criterion
            # must not read as adding one (spec §2.4).
            'key': str(item.get('key') or f'c{index + 1}'),
            'label': label,
            'backed_by_source': bool(item.get('backed_by_source')),
            'quantified': bool(item.get('quantified')),
            'weight': weight,
        })

    return {
        'alternatives': _strings('alternatives'),
        'criteria': criteria,
        'assumptions': _strings('assumptions'),
        'risks': _strings('risks'),
        'dependencies': _strings('dependencies'),
        'sources': _strings('sources'),
        'confirmed': bool(raw.get('confirmed')),
    }


@decision_impact_bp.route('/baseline/<thread_id>', methods=['GET'])
@jwt_required()
def read_baseline(thread_id):
    """The baseline for a thread: the draft, or the sealed row once sealed."""
    user = _current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404

    baseline = get_baseline(user.id, thread_id)
    if baseline is None:
        try:
            baseline = capture_or_update_draft(user, thread_id)
        except LookupError as exc:
            return jsonify({'error': str(exc)}), 404
        except SealedBaselineError as exc:
            # Analysis already ran and no draft was ever taken. Seal what was
            # actually submitted rather than refusing the user a baseline.
            baseline = seal_baseline(user, thread_id, sealed_by=SEALED_BY_ANALYSIS)
            return jsonify({
                'baseline': baseline.to_dict(include_submission=True),
                'editable': False,
                'note': str(exc),
            }), 200

    return jsonify({
        'baseline': baseline.to_dict(include_submission=True),
        'editable': not baseline.is_sealed,
    }), 200


@decision_impact_bp.route('/baseline/<thread_id>', methods=['POST'])
@jwt_required()
def update_baseline(thread_id):
    """Revise the unsealed draft — the correction window's write path.

    Corrections shrink the delta we can later report, which is exactly why the
    window exists (spec §3.3). Never blocks anything: a user who ignores it
    still gets analysis, and still gets a report.
    """
    user = _current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404

    payload = request.get_json(silent=True) or {}
    structure = _clean_structure(payload.get('structure'))
    try:
        baseline = capture_or_update_draft(user, thread_id, structure=structure)
    except LookupError as exc:
        return jsonify({'error': str(exc)}), 404
    except SealedBaselineError as exc:
        return jsonify({'error': str(exc), 'code': 'baseline_sealed'}), 409

    return jsonify({'baseline': baseline.to_dict(include_submission=True)}), 200


@decision_impact_bp.route('/baseline/<thread_id>/seal', methods=['POST'])
@jwt_required()
def seal(thread_id):
    """Confirm the baseline. Idempotent."""
    user = _current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    try:
        baseline = seal_baseline(user, thread_id, sealed_by=SEALED_BY_USER)
    except LookupError as exc:
        return jsonify({'error': str(exc)}), 404
    return jsonify({'baseline': baseline.to_dict(include_submission=True)}), 200


@decision_impact_bp.route('/report/<thread_id>', methods=['GET'])
@jwt_required()
def report(thread_id):
    """The Decision Impact Report.

    Seals an unsealed baseline first when analysis has already produced output.
    The correction window has closed by then in any case, so this changes
    nothing about the content — it records the seal that should already have
    happened at the analysis call site (see the deferred wiring note in the
    spec's Phase 1 scope).
    """
    user = _current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404

    baseline = get_baseline(user.id, thread_id)
    if baseline is None or not baseline.is_sealed:
        from ..decision_impact import _thread_sources
        session, thread_data = _thread_sources(user.id, thread_id)
        if session is None and not thread_data:
            return jsonify({'error': f'No conversation found for thread {thread_id}'}), 404
        if not analysis_has_started(session, thread_data):
            return jsonify({
                'error': 'This decision has not been analyzed yet, so there is nothing to '
                         'compare the baseline against.',
                'code': 'analysis_not_started',
            }), 409
        seal_baseline(user, thread_id, sealed_by=SEALED_BY_ANALYSIS)

    try:
        payload = build_impact_report(user, thread_id)
    except LookupError as exc:
        return jsonify({'error': str(exc)}), 404
    except ValueError as exc:
        # Integrity failure. No report is better than a report that looks like
        # evidence and is not (spec §3.5).
        return jsonify({'error': str(exc), 'code': 'baseline_integrity_failed'}), 409

    return jsonify({'report': payload}), 200
