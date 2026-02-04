# app/guest_mode.py
import os
from flask import request

def install_guest_mode(app):
    # Enabled only when env DEMO_GUEST_MODE is truthy (1/true/yes)
    flag = str(os.getenv("DEMO_GUEST_MODE", "")).lower() in ("1","true","yes","on")
    if not flag:
        return

    @app.before_request
    def _guest_jwt_bridge():
        try:
            # Only synthesize a token for specific POST endpoints
            if request.method != "POST":
                return
            path = request.path or ""
            if not (
                path.startswith("/api/market-iq/analyze")
                or path.startswith("/api/market-iq/scenario")
                or path.startswith("/api/chat")
            ):
                return

            # If the client already provided Authorization or our login cookie, do nothing
            if "Authorization" in request.headers or request.cookies.get("sekki_access"):
                return

            # Fabricate a short-lived guest token and inject as an Authorization header
            from flask_jwt_extended import create_access_token
            tok = create_access_token(identity="guest", additional_claims={"role":"guest"})
            request.environ["HTTP_AUTHORIZATION"] = f"Bearer {tok}"
        except Exception:
            # Never break the request pipeline
            pass
