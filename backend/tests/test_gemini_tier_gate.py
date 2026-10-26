"""Business/Enterprise customer content never reaches Gemini's free tier;
upgrading is configuration only (GEMINI_API_TIER=paid). No network calls."""

import contextvars
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.models import Organization, OrganizationMember

from tests.test_session_org_ownership import _mk_user


def _gate():
    from app.routes import ai_agent
    return ai_agent


@pytest.fixture
def gemini_config(app):
    saved = {key: app.config.get(key) for key in ('GEMINI_API_KEY', 'GEMINI_API_TIER')}
    app.config['GEMINI_API_KEY'] = 'synthetic-test-key'
    app.config['GEMINI_API_TIER'] = 'free'
    yield app
    app.config.update(saved)


def _user_on_plan(db, email, plan_key):
    user = _mk_user(db, email)
    org = Organization(name=plan_key, owner_user_id=user.id, plan_key=plan_key)
    db.session.add(org)
    db.session.flush()
    db.session.add(OrganizationMember(organization_id=org.id, user_id=user.id, role='owner', status='active'))
    user.active_organization_id = org.id
    db.session.commit()
    return user


@pytest.mark.parametrize('plan_key', ['business', 'enterprise_custom'])
def test_free_tier_is_withheld_from_enterprise_customer_content(app, db, gemini_config, plan_key):
    user = _user_on_plan(db, f'{plan_key}@ent.test', plan_key)
    with app.app_context(), _gate().ai_customer_scope(user.id):
        assert _gate().gemini_permitted_for_customer() is False
        assert _gate()._gemini_api_key() is None


def test_other_plans_keep_today_s_gemini_fallback(app, db, gemini_config):
    user = _user_on_plan(db, 'team@ent.test', 'team')
    with app.app_context(), _gate().ai_customer_scope(user.id):
        assert _gate()._gemini_api_key() == 'synthetic-test-key'


def test_paid_tier_is_a_configuration_switch(app, db, gemini_config):
    user = _user_on_plan(db, 'paid@ent.test', 'enterprise_custom')
    app.config['GEMINI_API_TIER'] = 'paid'
    with app.app_context(), _gate().ai_customer_scope(user.id):
        assert _gate()._gemini_api_key() == 'synthetic-test-key'


def test_scope_follows_work_into_worker_threads(app, db, gemini_config):
    user = _user_on_plan(db, 'pool@ent.test', 'enterprise_custom')

    def in_worker():
        with app.app_context():
            return _gate()._gemini_api_key()

    with app.app_context(), _gate().ai_customer_scope(user.id):
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(contextvars.copy_context().run, in_worker).result() is None


def test_signed_in_request_is_recognized(client, app, db, gemini_config):
    from flask_jwt_extended import create_access_token
    user = _user_on_plan(db, 'request@ent.test', 'enterprise_custom')
    with app.app_context():
        token = create_access_token(identity=str(user.id))
    with app.test_request_context(headers={'Authorization': f'Bearer {token}'}):
        from flask_jwt_extended import verify_jwt_in_request
        verify_jwt_in_request()
        assert _gate().gemini_permitted_for_customer() is False
