import base64
import hashlib
import os
import secrets
from urllib.parse import urlencode

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from app.connector_runtime import request_json_with_backoff
from app.connector_store import get_connector_settings, update_connector_settings


DEFAULT_SALESFORCE_AUTH_BASE_URL = "https://login.salesforce.com"



def _text(value):
    return str(value or "").strip()



def _state_serializer(secret):
    if not secret:
        raise RuntimeError("Missing secret key for Salesforce OAuth state signing")
    return URLSafeTimedSerializer(secret_key=secret, salt="salesforce-oauth-state")



def encode_salesforce_oauth_state(secret, payload):
    serializer = _state_serializer(secret)
    return serializer.dumps(payload or {})



def decode_salesforce_oauth_state(secret, state_token, max_age_seconds=900):
    serializer = _state_serializer(secret)
    if not state_token:
        raise BadSignature("Missing OAuth state")
    return serializer.loads(state_token, max_age=max_age_seconds)



def salesforce_runtime_config(user_id):
    settings = get_connector_settings(user_id, "salesforce_insights")
    auth_base = _text(settings.get("salesforce_auth_base_url") or os.getenv("SALESFORCE_AUTH_BASE_URL") or DEFAULT_SALESFORCE_AUTH_BASE_URL).rstrip("/")
    return {
        "instance_url": _text(settings.get("salesforce_instance_url") or os.getenv("SALESFORCE_INSTANCE_URL")).rstrip("/"),
        "client_id": _text(settings.get("salesforce_client_id") or os.getenv("SALESFORCE_CLIENT_ID")),
        "client_secret": _text(settings.get("salesforce_client_secret") or os.getenv("SALESFORCE_CLIENT_SECRET")),
        "refresh_token": _text(settings.get("salesforce_refresh_token") or os.getenv("SALESFORCE_REFRESH_TOKEN")),
        "access_token": _text(settings.get("salesforce_access_token") or os.getenv("SALESFORCE_ACCESS_TOKEN")),
        "token_type": _text(settings.get("salesforce_token_type") or "Bearer") or "Bearer",
        "auth_base_url": auth_base,
    }



def salesforce_missing_oauth_config(config):
    missing = []
    for key in ("client_id", "client_secret"):
        if not _text(config.get(key)):
            missing.append(f"salesforce_{key}")
    return missing



def generate_pkce_pair():
    """Return (code_verifier, code_challenge) for OAuth PKCE."""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode("utf-8")
    digest = hashlib.sha256(code_verifier.encode("utf-8")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("utf-8")
    return code_verifier, code_challenge


def salesforce_authorize_url(config, state_token, redirect_uri, scope=None, code_challenge=None):
    base = _text(config.get("auth_base_url") or DEFAULT_SALESFORCE_AUTH_BASE_URL).rstrip("/")
    query = {
        "response_type": "code",
        "client_id": config.get("client_id"),
        "redirect_uri": redirect_uri,
        "state": state_token,
    }
    requested_scope = _text(scope) or "refresh_token api offline_access"
    if requested_scope:
        query["scope"] = requested_scope
    if code_challenge:
        query["code_challenge"] = code_challenge
        query["code_challenge_method"] = "S256"
    return f"{base}/services/oauth2/authorize?{urlencode(query)}"



def exchange_salesforce_code(config, code, redirect_uri, code_verifier=None):
    base = _text(config.get("auth_base_url") or DEFAULT_SALESFORCE_AUTH_BASE_URL).rstrip("/")
    token_url = f"{base}/services/oauth2/token"

    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": config.get("client_id"),
        "client_secret": config.get("client_secret"),
        "redirect_uri": redirect_uri,
    }
    if code_verifier:
        payload["code_verifier"] = code_verifier

    result = request_json_with_backoff(
        "POST",
        token_url,
        data_payload=payload,
        headers={"Accept": "application/json"},
        timeout=20,
        max_attempts=3,
    )
    return result["data"], result



def refresh_salesforce_access_token(config):
    base = _text(config.get("auth_base_url") or DEFAULT_SALESFORCE_AUTH_BASE_URL).rstrip("/")
    token_url = f"{base}/services/oauth2/token"

    result = request_json_with_backoff(
        "POST",
        token_url,
        data_payload={
            "grant_type": "refresh_token",
            "refresh_token": config.get("refresh_token"),
            "client_id": config.get("client_id"),
            "client_secret": config.get("client_secret"),
        },
        headers={"Accept": "application/json"},
        timeout=20,
        max_attempts=3,
    )
    return result["data"], result



def _ensure_access_token(user_id):
    config = salesforce_runtime_config(user_id)
    access_token = _text(config.get("access_token"))
    if access_token:
        return config, None

    if not _text(config.get("refresh_token")):
        raise RuntimeError("Salesforce is not connected. Refresh token missing.")

    token_data, _ = refresh_salesforce_access_token(config)
    new_access_token = _text(token_data.get("access_token"))
    if not new_access_token:
        raise RuntimeError("Failed to refresh Salesforce access token.")

    updates = {
        "salesforce_access_token": new_access_token,
        "salesforce_token_type": _text(token_data.get("token_type") or "Bearer") or "Bearer",
    }
    if _text(token_data.get("instance_url")):
        updates["salesforce_instance_url"] = _text(token_data.get("instance_url"))

    update_connector_settings(user_id, "salesforce_insights", updates)
    config = salesforce_runtime_config(user_id)
    return config, token_data



def _authorized_headers(config):
    token_type = _text(config.get("token_type") or "Bearer") or "Bearer"
    return {
        "Accept": "application/json",
        "Authorization": f"{token_type} {config.get('access_token')}",
    }



def query_salesforce(user_id, soql):
    config, token_refresh_payload = _ensure_access_token(user_id)
    instance_url = _text(config.get("instance_url")).rstrip("/")
    if not instance_url:
        raise RuntimeError("Salesforce instance URL is not configured.")

    query_result = request_json_with_backoff(
        "GET",
        f"{instance_url}/services/data/v60.0/query",
        params={"q": soql},
        headers=_authorized_headers(config),
        timeout=20,
        max_attempts=3,
    )
    return query_result["data"], query_result, token_refresh_payload



def fetch_pipeline_summary(user_id, lookback_days=90, max_records=200):
    days = max(1, min(int(lookback_days or 90), 365))
    limit = max(1, min(int(max_records or 200), 2000))
    soql = (
        "SELECT Id, Name, StageName, Amount, CloseDate, Probability, IsClosed "
        "FROM Opportunity "
        f"WHERE IsDeleted = false AND CloseDate = LAST_N_DAYS:{days} "
        "ORDER BY CloseDate DESC "
        f"LIMIT {limit}"
    )
    payload, query_meta, token_refresh_payload = query_salesforce(user_id, soql)
    records = payload.get("records") if isinstance(payload.get("records"), list) else []

    totals = {
        "opportunity_count": len(records),
        "open_count": 0,
        "closed_count": 0,
        "total_amount": 0.0,
        "weighted_amount": 0.0,
        "stages": {},
    }

    for row in records:
        if not isinstance(row, dict):
            continue
        stage = _text(row.get("StageName") or "Unknown") or "Unknown"
        amount = row.get("Amount")
        probability = row.get("Probability")
        is_closed = bool(row.get("IsClosed"))

        try:
            amount_value = float(amount) if amount is not None else 0.0
        except Exception:
            amount_value = 0.0
        try:
            probability_value = float(probability) if probability is not None else 0.0
        except Exception:
            probability_value = 0.0

        totals["total_amount"] += amount_value
        totals["weighted_amount"] += amount_value * (probability_value / 100.0)
        if is_closed:
            totals["closed_count"] += 1
        else:
            totals["open_count"] += 1

        stage_row = totals["stages"].setdefault(stage, {"count": 0, "amount": 0.0})
        stage_row["count"] += 1
        stage_row["amount"] += amount_value

    stage_breakdown = [
        {"stage": key, "count": value["count"], "amount": round(value["amount"], 2)}
        for key, value in sorted(
            totals["stages"].items(),
            key=lambda item: item[1]["amount"],
            reverse=True,
        )
    ]

    summary = {
        "lookback_days": days,
        "opportunity_count": totals["opportunity_count"],
        "open_count": totals["open_count"],
        "closed_count": totals["closed_count"],
        "total_amount": round(totals["total_amount"], 2),
        "weighted_amount": round(totals["weighted_amount"], 2),
        "stage_breakdown": stage_breakdown,
    }

    return {
        "summary": summary,
        "records": records,
        "soql": soql,
        "attempt_count": query_meta.get("attempt_count"),
        "duration_ms": query_meta.get("duration_ms"),
        "token_refreshed": bool(token_refresh_payload),
    }


__all__ = [
    "BadSignature",
    "SignatureExpired",
    "decode_salesforce_oauth_state",
    "encode_salesforce_oauth_state",
    "exchange_salesforce_code",
    "fetch_pipeline_summary",
    "salesforce_authorize_url",
    "salesforce_missing_oauth_config",
    "salesforce_runtime_config",
]
