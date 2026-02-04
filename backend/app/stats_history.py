from datetime import datetime
from flask import Blueprint, request, jsonify, current_app
from sqlalchemy import Integer, String, DateTime
from sqlalchemy.dialects.postgresql import JSONB
from . import db

stats_history_bp = Blueprint('stats_history_bp', __name__, url_prefix='/api/statistical-analysis/history')

try:
    JSONType = JSONB
except Exception:
    from sqlalchemy.types import JSON as JSONType

class StatsHistory(db.Model):
    __tablename__ = 'stats_history'
    id = db.Column(Integer, primary_key=True)
    user_id = db.Column(String(128), index=True, nullable=True)
    # natural key for de-dupe: you can post same client id to update
    client_id = db.Column(String(128), index=True, nullable=True, unique=True)
    title = db.Column(String(256), nullable=True)
    tests_count = db.Column(Integer, nullable=True)
    blob = db.Column(JSONType, nullable=True)  # optional payload (filename, cols, etc.)
    created = db.Column(DateTime, default=datetime.utcnow, nullable=False)
    updated = db.Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

def _ensure_tables():
    try:
        db.create_all()
    except Exception as e:
        current_app.logger.warning("stats_history.create_all: %s", e)

def _user_from_authz():
    # Minimal partitioning by bearer token fingerprint; swap to real user if you have JWT claims
    auth = request.headers.get('Authorization', '')
    return auth[-40:] if auth else None

@stats_history_bp.route('', methods=['GET'])
def list_history():
    _ensure_tables()
    uid = _user_from_authz()
    q = StatsHistory.query
    if uid:
        q = q.filter_by(user_id=uid)
    rows = q.order_by(StatsHistory.updated.desc()).limit(200).all()
    out = []
    for r in rows:
        out.append({
            "id": r.id,
            "client_id": r.client_id,
            "title": r.title,
            "testsCount": r.tests_count,
            "createdAt": r.created.isoformat(),
            "updatedAt": r.updated.isoformat(),
            "blob": r.blob or {},
        })
    return jsonify({"success": True, "items": out})

@stats_history_bp.route('', methods=['POST'])
def upsert_history():
    _ensure_tables()
    uid = _user_from_authz()
    j = request.get_json(force=True, silent=False) or {}
    cid = j.get("client_id")
    if not cid:
        return jsonify({"success": False, "error": "missing client_id"}), 400

    row = StatsHistory.query.filter_by(client_id=cid).first()
    if not row:
        row = StatsHistory(client_id=cid, user_id=uid)
        db.session.add(row)

    if "title" in j and j["title"]: row.title = j["title"]
    if "testsCount" in j and j["testsCount"] is not None: row.tests_count = int(j["testsCount"])
    if "blob" in j and j["blob"] is not None: row.blob = j["blob"]
    db.session.commit()
    return jsonify({"success": True, "id": row.id, "client_id": row.client_id})

@stats_history_bp.route('/<client_id>', methods=['DELETE'])
def delete_history(client_id):
    _ensure_tables()
    row = StatsHistory.query.filter_by(client_id=client_id).first()
    if not row:
        return jsonify({"success": False, "error": "not_found"}), 404
    db.session.delete(row)
    db.session.commit()
    return jsonify({"success": True})
