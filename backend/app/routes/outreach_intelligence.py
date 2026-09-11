import os

import requests
from flask import Blueprint, jsonify, request


outreach_intelligence_bp = Blueprint("outreach_intelligence", __name__)

_DEFAULT_SERVICE_URL = "http://127.0.0.1:8091"


def _service_url(path: str) -> str:
    base = os.environ.get("JASPEN_OUTREACH_SERVICE_URL", _DEFAULT_SERVICE_URL)
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


@outreach_intelligence_bp.route("/health", methods=["GET"])
def health():
    try:
        response = requests.get(_service_url("/health"), timeout=5)
        response.raise_for_status()
        return jsonify(response.json()), 200
    except (requests.RequestException, ValueError):
        return jsonify({"status": "unavailable"}), 503


@outreach_intelligence_bp.route("/qualify", methods=["POST"])
def qualify():
    shared_secret = request.headers.get("X-Jaspen-Outreach-Secret", "")
    if not shared_secret:
        return jsonify({"error": "Unauthorized"}), 401

    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "A JSON request body is required"}), 400

    try:
        response = requests.post(
            _service_url("/v1/qualify"),
            headers={"X-Jaspen-Outreach-Secret": shared_secret},
            json=payload,
            timeout=55,
        )
    except requests.RequestException:
        return jsonify({"error": "Qualification service unavailable"}), 503

    try:
        body = response.json()
    except ValueError:
        body = {"error": "Qualification service returned an invalid response"}

    return jsonify(body), response.status_code
