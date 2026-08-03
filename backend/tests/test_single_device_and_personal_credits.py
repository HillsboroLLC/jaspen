"""The 300K credits are personal, and the account is the thing that proves it.

Two rules hold that line: an account carrying the offer can only be signed in
one place at a time, and nobody but the buyer can ever spend those credits -
including the shared pool of a Team plan they later join.
"""
import pytest
from werkzeug.security import generate_password_hash

from app.billing_config import apply_plan_to_user, consume_credits, get_usage_meter_state
from app.founder_entitlements import (
    grant_limited_time_300k_offer,
    limited_time_300k_credit_balance,
    persistent_credit_balance,
)
from app.models import User, UserAuthSession
from app.orgs import ensure_default_organization_for_user

PASSWORD = 'ValidPass1'


@pytest.fixture(autouse=True)
def _no_login_rate_limit():
    """These tests sign in far more often than a human would."""
    from app import limiter

    previous = limiter.enabled
    limiter.enabled = False
    yield
    limiter.enabled = previous


@pytest.fixture
def buyer(db, test_user):
    """test_user, holding the 300K offer."""
    grant_limited_time_300k_offer(test_user, 300_000_000, payment_reference='pi_single_device')
    db.session.commit()
    return test_user


def _login(client, email='test@example.com', **extra):
    return client.post('/api/v1/auth/login', json={
        'email': email, 'password': PASSWORD, **extra,
    })


def _active_sessions(user):
    return UserAuthSession.query.filter_by(
        user_id=str(user.id), revoked_at=None,
    ).count()


# —— One device at a time ————————————————————————————————


def test_first_sign_in_is_never_blocked(client, db, buyer):
    response = _login(client)

    assert response.status_code == 200
    assert response.get_json()['token']


def test_second_device_is_refused_with_an_actionable_message(app, db, buyer):
    first = _login(app.test_client())
    second = _login(app.test_client())

    assert first.status_code == 200
    assert second.status_code == 409
    body = second.get_json()
    assert body['code'] == 'other_device_active'
    assert body['can_end_other_sessions'] is True
    assert 'already signed in on another device' in body['message']
    assert 'other_device' in body
    # No token is issued, so the second device gets no access at all.
    assert 'token' not in body


def test_taking_over_ends_the_other_session_and_signs_in_here(app, db, buyer):
    _login(app.test_client())
    assert _active_sessions(buyer) == 1

    takeover = _login(app.test_client(), end_other_sessions=True)

    assert takeover.status_code == 200
    assert takeover.get_json()['token']
    # Exactly one session survives: this one.
    assert _active_sessions(buyer) == 1


def test_the_evicted_device_can_no_longer_use_its_token(app, db, buyer):
    device_a = app.test_client()
    device_b = app.test_client()
    first = _login(device_a)
    headers = {'Authorization': f'Bearer {first.get_json()["token"]}'}
    assert device_a.get('/api/v1/auth/me', headers=headers).status_code == 200

    takeover = _login(device_b, end_other_sessions=True)
    assert takeover.status_code == 200

    # The first device's token is dead the moment the second one takes over.
    device_a.delete_cookie('access_token_cookie')
    assert device_a.get('/api/v1/auth/me', headers=headers).status_code == 401


def test_accounts_without_the_offer_may_use_several_devices(app, db, test_user):
    """The gate is tied to the personal credits, not applied to everyone."""
    first = _login(app.test_client())
    second = _login(app.test_client())

    assert first.status_code == 200
    assert second.status_code == 200
    assert _active_sessions(test_user) == 2


def test_signing_out_frees_the_account_for_the_next_device(app, db, buyer):
    device_a = app.test_client()
    first = _login(device_a)
    token = first.get_json()['token']

    device_a.post('/api/v1/auth/logout', headers={'Authorization': f'Bearer {token}'})
    second = _login(app.test_client())

    assert second.status_code == 200


# —— The credits stay personal on a Team plan ——————————————


def _teammate(db, organization_id):
    mate = User(
        email='teammate@example.com',
        name='Team Mate',
        password_hash=generate_password_hash(PASSWORD, method='pbkdf2:sha256'),
        subscription_plan='team',
        active_organization_id=organization_id,
    )
    db.session.add(mate)
    db.session.commit()
    return mate


def _pool_only_remaining(app, user):
    """The shared pool, with the user's personal grant taken back out.

    get_usage_meter_state deliberately reports one combined number to the UI.
    """
    combined = int(get_usage_meter_state(user, app.config).get('remaining') or 0)
    return combined - persistent_credit_balance(user)


def _put_on_a_team(app, db, buyer):
    ensure_default_organization_for_user(buyer)
    apply_plan_to_user(buyer, 'team', app.config, reset_credits=True)
    db.session.commit()
    return buyer.active_organization_id


def test_a_teammate_can_never_spend_the_buyers_300k(app, db, buyer):
    """The pool is shared; the personal grant is not."""
    _put_on_a_team(app, db, buyer)
    mate = _teammate(db, buyer.active_organization_id)

    assert limited_time_300k_credit_balance(buyer) == 300_000_000
    assert persistent_credit_balance(mate) == 0

    # Drain everything the teammate is allowed to spend.
    for _ in range(50):
        ok, _remaining = consume_credits(mate, 1_000_000)
        if not ok:
            break
    db.session.commit()

    # The buyer's personal credits are untouched by anything the teammate did.
    assert limited_time_300k_credit_balance(buyer) == 300_000_000
    assert persistent_credit_balance(mate) == 0


def test_team_pool_is_spent_before_the_buyers_personal_credits(app, db, buyer):
    _put_on_a_team(app, db, buyer)
    pooled_before = _pool_only_remaining(app, buyer)
    assert pooled_before > 0

    ok, _remaining = consume_credits(buyer, 1000)
    db.session.commit()

    assert ok is True
    # The pool absorbed it; the 300K is only reached once the pool is empty.
    assert limited_time_300k_credit_balance(buyer) == 300_000_000
    assert _pool_only_remaining(app, buyer) < pooled_before


def test_the_300k_survives_joining_and_carries_on_after_the_pool_empties(app, db, buyer):
    """Upgrading does not forfeit the credits, and they remain spendable."""
    _put_on_a_team(app, db, buyer)
    pooled = _pool_only_remaining(app, buyer)

    consume_credits(buyer, pooled)
    db.session.commit()
    assert limited_time_300k_credit_balance(buyer) == 300_000_000

    ok, _remaining = consume_credits(buyer, 5_000)
    db.session.commit()

    assert ok is True
    assert limited_time_300k_credit_balance(buyer) == 300_000_000 - 5_000
