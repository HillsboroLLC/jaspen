"""Google sign-in must not skip Jaspen's 2FA (SSO audit finding 6)."""
import sys

import pyotp


class _Response:
    def __init__(self, payload, *, ok=True, status_code=200):
        self._payload = payload
        self.ok = ok
        self.status_code = status_code
        self.content = b'{}'

    def json(self):
        return self._payload


def _google_sign_in(client, app, monkeypatch, email):
    auth = sys.modules['app.routes.auth']
    app.config['GOOGLE_CLIENT_ID'] = 'test-client'
    app.config['GOOGLE_CLIENT_SECRET'] = 'test-secret'
    monkeypatch.setattr(auth.requests, 'post', lambda *a, **k: _Response({'access_token': 'google-token'}))
    monkeypatch.setattr(auth.requests, 'get', lambda *a, **k: _Response({
        'email': email, 'email_verified': True, 'name': 'Test User',
    }))
    with app.test_request_context():
        state = auth._google_state_serializer().dumps({'next': '/new'})
    return client.get(f'/api/v1/auth/google/callback?code=abc&state={state}')


def test_google_sign_in_with_2fa_on_goes_through_the_challenge(client, app, db, test_user, monkeypatch):
    auth = sys.modules['app.routes.auth']
    secret = pyotp.random_base32()
    test_user.mfa_secret = auth._encrypt_mfa_secret(secret)
    test_user.mfa_enabled = True
    db.session.commit()

    response = _google_sign_in(client, app, monkeypatch, test_user.email)

    assert response.status_code == 302
    assert 'mfa=1' in response.headers['Location']
    assert 'mfa_pending' not in response.headers['Location']  # never in the URL
    assert client.get_cookie(app.config['JWT_ACCESS_COOKIE_NAME']) is None

    pending = client.get('/api/v1/auth/mfa/pending')
    assert pending.status_code == 200
    body = pending.get_json()
    assert body['mfa_required'] is True and body['mfa_setup_required'] is False
    assert body['pending_token']
    # One-time: the cookie is cleared once read.
    assert client.get('/api/v1/auth/mfa/pending').status_code == 401

    challenged = client.post('/api/v1/auth/mfa/challenge', json={
        'pending_token': body['pending_token'], 'code': pyotp.TOTP(secret).now(),
    })
    assert challenged.status_code == 200, challenged.get_json()
    assert client.get_cookie(app.config['JWT_ACCESS_COOKIE_NAME']) is not None


def test_google_sign_in_without_2fa_still_signs_in_directly(client, app, db, test_user, monkeypatch):
    response = _google_sign_in(client, app, monkeypatch, test_user.email)
    assert response.status_code == 302
    assert 'mfa=1' not in response.headers['Location']
    assert client.get_cookie(app.config['JWT_ACCESS_COOKIE_NAME']) is not None


def test_pending_endpoint_without_a_google_sign_in_is_refused(client):
    assert client.get('/api/v1/auth/mfa/pending').status_code == 401


def test_google_token_failure_does_not_log_provider_payload(client, app, monkeypatch, caplog):
    auth = sys.modules['app.routes.auth']
    app.config['GOOGLE_CLIENT_ID'] = 'test-client'
    app.config['GOOGLE_CLIENT_SECRET'] = 'test-secret'
    provider_token = 'provider-' + ('credential-' * 4)
    monkeypatch.setattr(
        auth.requests,
        'post',
        lambda *a, **k: _Response(
            {'access_token': provider_token, 'error_description': provider_token},
            ok=False,
            status_code=401,
        ),
    )
    with app.test_request_context():
        state = auth._google_state_serializer().dumps({'next': '/new'})

    response = client.get(f'/api/v1/auth/google/callback?code=abc&state={state}')

    assert response.status_code == 302
    assert provider_token not in caplog.text
    assert 'status=401' in caplog.text
