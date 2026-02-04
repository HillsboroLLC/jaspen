# app/jwt_callbacks.py
from flask import request, current_app

def _client_ip():
    # X-Forwarded-For aware (first hop)
    xff = request.headers.get("X-Forwarded-For","").split(",")[0].strip()
    return xff or request.remote_addr

def install_jwt_error_logs(jwt, app):
    @jwt.unauthorized_loader
    def _unauth(msg):
        app.logger.warning("JWT unauthorized: path=%s ip=%s hdr_Authorization=%s cookies=%s msg=%s",
                           request.path, _client_ip(),
                           bool(request.headers.get("Authorization")),
                           ";".join(request.cookies.keys()), msg)
        return {"message": "missing_token"}, 401

    @jwt.invalid_token_loader
    def _invalid(msg):
        app.logger.warning("JWT invalid: path=%s ip=%s msg=%s", request.path, _client_ip(), msg)
        return {"message": "invalid_token"}, 401

    @jwt.expired_token_loader
    def _expired(jwt_header, jwt_data):
        app.logger.warning("JWT expired: path=%s ip=%s sub=%s", request.path, _client_ip(), jwt_data.get("sub"))
        return {"message": "token_expired"}, 401

    @jwt.revoked_token_loader
    def _revoked(jwt_header, jwt_data):
        app.logger.warning("JWT revoked: path=%s ip=%s sub=%s", request.path, _client_ip(), jwt_data.get("sub"))
        return {"message": "token_revoked"}, 401

    @jwt.needs_fresh_token_loader
    def _needs_fresh(jwt_header, jwt_data):
        app.logger.warning("JWT needs_fresh: path=%s ip=%s sub=%s", request.path, _client_ip(), jwt_data.get("sub"))
        return {"message": "fresh_token_required"}, 401
