from flask import Blueprint, jsonify

health_bp = Blueprint("health", __name__)

@health_bp.route("/healthz", methods=["GET"])
def healthz():
    return jsonify(status="ok"), 200
