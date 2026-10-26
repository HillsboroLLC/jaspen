"""Small WorkOS SSO boundary; tests replace this client and make no network calls."""

from urllib.parse import urlencode

import requests
from flask import current_app


class SsoProviderError(RuntimeError):
    pass


class WorkOsSsoClient:
    authorize_endpoint = "https://api.workos.com/sso/authorize"
    token_endpoint = "https://api.workos.com/sso/token"

    def __init__(self, *, client_id, api_key, redirect_uri):
        self.client_id = str(client_id or '').strip()
        self.api_key = str(api_key or '').strip()
        self.redirect_uri = str(redirect_uri or '').strip()
        if not self.client_id or not self.api_key or not self.redirect_uri:
            raise SsoProviderError("SSO provider is not configured")

    def authorization_url(self, *, organization_id, state):
        query = urlencode({
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "organization": organization_id,
            "state": state,
        })
        return f"{self.authorize_endpoint}?{query}"

    def authenticate(self, *, code):
        response = requests.post(
            self.token_endpoint,
            headers={"Authorization": f"Bearer {self.api_key}"},
            data={
                "client_id": self.client_id,
                "client_secret": self.api_key,
                "code": code,
                "grant_type": "authorization_code",
            },
            timeout=10,
        )
        if not response.ok:
            raise SsoProviderError(f"SSO token exchange failed ({response.status_code})")
        payload = response.json() if response.content else {}
        profile = payload.get("profile") if isinstance(payload, dict) else None
        if not isinstance(profile, dict):
            raise SsoProviderError("SSO provider returned no profile")
        return profile


def get_sso_client():
    factory = current_app.config.get("SSO_CLIENT_FACTORY")
    if callable(factory):
        return factory()
    return WorkOsSsoClient(
        client_id=current_app.config.get("WORKOS_CLIENT_ID"),
        api_key=current_app.config.get("WORKOS_API_KEY"),
        redirect_uri=current_app.config.get("WORKOS_REDIRECT_URI"),
    )
