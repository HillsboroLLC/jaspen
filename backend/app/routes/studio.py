# backend/app/routes/studio.py
#
# "Studio" — the clean, compartmentalized idea-vetting flow. See
# docs/STUDIO_BUILD_PLAN.md. Standalone artifacts on a thin per-session workspace
# parent; no thread/bundle blob, no baseline/scenario hierarchy.
#
# Phase 1 routes (this file):
#   POST   /api/v1/studio/workspaces                 create a workspace (session)
#   GET    /api/v1/studio/workspaces                 list my workspaces
#   GET    /api/v1/studio/workspaces/<id>            load workspace + its artifacts
#   PUT    /api/v1/studio/workspaces/<id>/rubric     set the USER's rubric (+groups)
#   POST   /api/v1/studio/workspaces/<id>/score      one-pass score 1..N ideas
#
# The deterministic scoring engine is reused verbatim from strategy.py (same math,
# same results); it will move into services/scoring.py during cleanup (P6).

import re
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity

from .. import db
from ..models import User
from ..models_studio import StudioWorkspace, StudioArtifact

studio_bp = Blueprint('studio', __name__)


# ----------------------------- helpers --------------------------------------

def _slugify(text):
    s = re.sub(r"[^a-z0-9]+", "_", str(text or "").strip().lower()).strip("_")
    return s or "criterion"


def _coerce_weight(v):
    if isinstance(v, bool):
        return 0.0
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str):
        m = re.search(r"-?\d+(?:\.\d+)?", v)
        return float(m.group()) if m else 0.0
    return 0.0


def _normalize_rubric(raw_criteria):
    """Turn whatever the USER provided into a clean rubric. The app does not invent
    criteria — it only normalizes what the user gives (label, weight, optional group,
    is_risk, description). Returns {"criteria": [...]} or None if < 2 valid."""
    if isinstance(raw_criteria, dict):
        if isinstance(raw_criteria.get("criteria"), list):
            raw_criteria = raw_criteria["criteria"]
        else:
            raw_criteria = [{"label": k, "weight": v} for k, v in raw_criteria.items()]
    if not isinstance(raw_criteria, list):
        return None

    criteria = []
    used = set()
    for c in raw_criteria:
        if isinstance(c, str):
            c = {"label": c}
        if not isinstance(c, dict):
            continue
        label = str(
            c.get("label") or c.get("name") or c.get("criterion")
            or c.get("variable") or c.get("factor") or ""
        ).strip()
        if not label:
            continue
        key = _slugify(label)
        while key in used:
            key = f"{key}_2"
        used.add(key)
        weight = max(0.0, _coerce_weight(
            c.get("weight", c.get("weight_pct", c.get("percentage", c.get("pct", 0))))
        ))
        group = str(c.get("group") or c.get("category") or c.get("bucket") or "").strip() or None
        criteria.append({
            "key": key,
            "label": label,
            "weight": weight,
            "is_risk": bool(c.get("is_risk")),
            "group": group,
            "description": (str(c.get("description") or c.get("notes") or "").strip() or None),
        })

    if len(criteria) < 2:
        return None
    total = sum(c["weight"] for c in criteria) or 1.0
    for c in criteria:
        c["weight"] = round(c["weight"] / total, 4)
    return {"criteria": criteria, "source": "user", "created_at": datetime.utcnow().isoformat()}


def _current_user():
    user_id = get_jwt_identity()
    return user_id, User.query.get(user_id)


def _owned_workspace(user_id, workspace_id):
    return StudioWorkspace.query.filter_by(
        id=str(workspace_id), user_id=str(user_id), archived_at=None
    ).first()


# ----------------------------- routes ---------------------------------------

@studio_bp.route('/workspaces', methods=['POST'])
@jwt_required()
def create_workspace():
    """Create a new per-session workspace (fresh rubric, fresh cards each time)."""
    user_id, user = _current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    body = request.get_json(silent=True) or {}
    title = str(body.get('title') or '').strip() or 'Untitled evaluation'
    ws = StudioWorkspace(
        user_id=user_id,
        organization_id=getattr(user, 'active_organization_id', None),
        created_by_user_id=user_id,
        title=title,
        rubric={},
    )
    db.session.add(ws)
    db.session.commit()
    return jsonify({'ok': True, 'workspace': ws.to_dict()}), 201


@studio_bp.route('/workspaces', methods=['GET'])
@jwt_required()
def list_workspaces():
    user_id, _ = _current_user()
    rows = (
        StudioWorkspace.query
        .filter_by(user_id=user_id, archived_at=None)
        .order_by(StudioWorkspace.updated_at.desc())
        .limit(200)
        .all()
    )
    return jsonify({'ok': True, 'workspaces': [w.to_dict() for w in rows]})


@studio_bp.route('/workspaces/<workspace_id>', methods=['GET'])
@jwt_required()
def get_workspace(workspace_id):
    user_id, _ = _current_user()
    ws = _owned_workspace(user_id, workspace_id)
    if not ws:
        return jsonify({'error': 'Workspace not found'}), 404
    return jsonify({'ok': True, 'workspace': ws.to_dict(include_artifacts=True)})


@studio_bp.route('/workspaces/<workspace_id>/rubric', methods=['PUT'])
@jwt_required()
def set_rubric(workspace_id):
    """Store the USER's rubric (criteria + weights + optional groups). The app never
    fabricates criteria — it normalizes what the user provides."""
    user_id, _ = _current_user()
    ws = _owned_workspace(user_id, workspace_id)
    if not ws:
        return jsonify({'error': 'Workspace not found'}), 404
    body = request.get_json(silent=True) or {}
    rubric = _normalize_rubric(body.get('criteria') if body.get('criteria') is not None else body.get('rubric'))
    if not rubric:
        return jsonify({'error': 'Provide at least 2 criteria, each with a label and weight.'}), 400
    ws.rubric = rubric
    if 'theme' in body and isinstance(body.get('theme'), dict):
        ws.theme = body['theme']
    if body.get('autogenerate_confidence') is not None:
        try:
            ws.autogenerate_confidence = max(0, min(100, int(body['autogenerate_confidence'])))
        except (TypeError, ValueError):
            pass
    if str(body.get('title') or '').strip():
        ws.title = str(body['title']).strip()
    db.session.commit()
    return jsonify({'ok': True, 'workspace': ws.to_dict()})


@studio_bp.route('/workspaces/<workspace_id>/score', methods=['POST'])
@jwt_required()
def score_ideas(workspace_id):
    """One-pass deterministic scoring of 1..N ideas against the workspace rubric.
    Each idea becomes its OWN standalone scorecard artifact row."""
    user_id, user = _current_user()
    if not user:
        return jsonify({'error': 'User not found'}), 404
    ws = _owned_workspace(user_id, workspace_id)
    if not ws:
        return jsonify({'error': 'Workspace not found'}), 404

    body = request.get_json(silent=True) or {}
    raw_ideas = body.get('ideas') if isinstance(body.get('ideas'), list) else []
    ideas = []
    for it in raw_ideas:
        if isinstance(it, str):
            it = {'name': it}
        if not isinstance(it, dict):
            continue
        name = str(it.get('name') or it.get('idea') or it.get('label') or '').strip()
        if not name:
            continue
        ideas.append({
            'name': name,
            'description': str(it.get('description') or it.get('notes') or '').strip() or name,
            'locked': bool(it.get('locked') or it.get('required') or it.get('anchor')),
        })
    if not ideas:
        return jsonify({'error': 'Provide at least one idea to score (each needs a name).'}), 400

    # Reuse the proven deterministic engine (same math as the rest of the app).
    from .strategy import (
        _generate_batch_scorecards, get_llm_client,
        _resolve_user_model_selection, _normalize_strategy_objective,
    )

    model_selection, model_error = _resolve_user_model_selection(user)
    if model_error:
        return jsonify(model_error), 403

    rubric = ws.rubric if isinstance(ws.rubric, dict) and ws.rubric.get('criteria') else None
    client = get_llm_client()
    cards, portfolio_summary = _generate_batch_scorecards(
        client, ideas, rubric=rubric, strategy_objective='balanced',
        model_selection=model_selection, llm_model=model_selection['llm_model'],
    )

    base_position = (
        db.session.query(db.func.coalesce(db.func.max(StudioArtifact.position), -1))
        .filter_by(workspace_id=ws.id).scalar()
    )
    try:
        next_pos = int(base_position) + 1
    except (TypeError, ValueError):
        next_pos = 0

    created = []
    for idea, payload in zip(ideas, cards):
        if not isinstance(payload, dict):
            continue
        art = StudioArtifact(
            workspace_id=ws.id,
            user_id=user_id,
            organization_id=getattr(user, 'active_organization_id', None),
            type='scorecard',
            name=idea['name'],
            data={**payload, 'project_description': idea['description'], 'locked': idea['locked']},
            position=next_pos,
        )
        next_pos += 1
        db.session.add(art)
        created.append(art)

    # Touch the workspace so it sorts to the top of the list.
    ws.updated_at = datetime.utcnow()
    db.session.commit()

    return jsonify({
        'ok': True,
        'scored': [a.to_dict() for a in created],
        'count': len(created),
        'portfolio_summary': portfolio_summary,
    })
