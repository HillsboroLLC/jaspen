"""Focused coverage for Redis-backed per-user AI conversation limits."""

from dataclasses import dataclass

import fakeredis
import pytest
import redis
from flask import Flask, jsonify
from flask_jwt_extended import JWTManager, create_access_token, get_jwt_identity, jwt_required
from flask_limiter import Limiter
from limits import RateLimitItemPerHour

from app.rate_limits import (
    AI_CONVERSATION_SCOPE,
    assert_rate_limit_storage_available,
    resolve_rate_limit_storage_uri,
    shared_limit_usage,
)


@dataclass
class _Harness:
    app: Flask
    limiter: Limiter
    ai_calls: dict
    credit_deductions: dict

    def token(self, user_id, account_id="shared-account"):
        with self.app.app_context():
            return create_access_token(
                identity=str(user_id),
                additional_claims={"account_id": account_id},
            )

    def post(self, path, token):
        return self.app.test_client().post(
            path,
            headers={"Authorization": f"Bearer {token}"},
        )


def _build_harness(fake_server, *, hourly="3 per hour", daily="100 per day"):
    app = Flask(__name__)
    app.config.update(
        TESTING=True,
        JWT_SECRET_KEY="shared-rate-limit-test-secret-long-enough-for-hs256",
    )
    JWTManager(app)

    pool = redis.ConnectionPool(
        connection_class=fakeredis.FakeConnection,
        server=fake_server,
    )
    limiter = Limiter(
        key_func=lambda: f"user:{get_jwt_identity()}",
        app=app,
        storage_uri="redis://",
        storage_options={"connection_pool": pool},
        in_memory_fallback_enabled=False,
        swallow_errors=False,
    )
    ai_calls = {}
    credit_deductions = {}

    def counted_response(action):
        user_id = str(get_jwt_identity())
        ai_calls[user_id] = ai_calls.get(user_id, 0) + 1
        credit_deductions[user_id] = credit_deductions.get(user_id, 0) + 1
        return jsonify({"action": action})

    def register_action(action, burst):
        endpoint = f"conversation_{action}"

        @app.post(f"/conversation/{action}", endpoint=endpoint)
        @jwt_required()
        @limiter.limit(burst)
        @limiter.shared_limit(hourly, scope=AI_CONVERSATION_SCOPE)
        @limiter.shared_limit(daily, scope=AI_CONVERSATION_SCOPE)
        def route():
            return counted_response(action)

    register_action("start", "3 per minute")
    register_action("continue", "10 per minute")
    register_action("regenerate", "3 per minute")
    return _Harness(app, limiter, ai_calls, credit_deductions)


@pytest.fixture
def fake_server():
    return fakeredis.FakeServer()


def test_start_continue_and_regenerate_share_hourly_counter(fake_server):
    harness = _build_harness(fake_server)
    token = harness.token("user-a")

    assert harness.post("/conversation/start", token).status_code == 200
    assert harness.post("/conversation/continue", token).status_code == 200
    assert harness.post("/conversation/regenerate", token).status_code == 200
    assert harness.post("/conversation/continue", token).status_code == 429

    used, _expiry = shared_limit_usage(
        harness.limiter,
        "user:user-a",
        RateLimitItemPerHour(3),
    )
    assert used == 4


def test_start_continue_and_regenerate_share_daily_counter(fake_server):
    harness = _build_harness(
        fake_server,
        hourly="100 per hour",
        daily="2 per day",
    )
    token = harness.token("daily-user")

    assert harness.post("/conversation/start", token).status_code == 200
    assert harness.post("/conversation/continue", token).status_code == 200
    assert harness.post("/conversation/regenerate", token).status_code == 429


def test_rate_limits_are_isolated_by_authenticated_user(fake_server):
    harness = _build_harness(fake_server, hourly="1 per hour")
    user_a = harness.token("user-a")
    user_b = harness.token("user-b")

    assert harness.post("/conversation/start", user_a).status_code == 200
    assert harness.post("/conversation/continue", user_a).status_code == 429
    assert harness.post("/conversation/continue", user_b).status_code == 200


def test_users_in_same_account_have_independent_limits(fake_server):
    harness = _build_harness(fake_server, hourly="1 per hour")
    first_member = harness.token("member-1", account_id="team-account")
    second_member = harness.token("member-2", account_id="team-account")

    assert harness.post("/conversation/start", first_member).status_code == 200
    assert harness.post("/conversation/continue", first_member).status_code == 429
    assert harness.post("/conversation/start", second_member).status_code == 200


def test_action_specific_minute_burst_limits_remain_separate(fake_server):
    harness = _build_harness(fake_server, hourly="100 per hour")
    token = harness.token("burst-user")

    assert [
        harness.post("/conversation/start", token).status_code
        for _ in range(4)
    ] == [200, 200, 200, 429]
    assert harness.post("/conversation/continue", token).status_code == 200


def test_redis_counters_are_shared_across_worker_instances(fake_server):
    worker_one = _build_harness(fake_server, hourly="2 per hour")
    worker_two = _build_harness(fake_server, hourly="2 per hour")
    token = worker_one.token("multi-worker-user")

    assert worker_one.post("/conversation/start", token).status_code == 200
    assert worker_two.post("/conversation/continue", token).status_code == 200
    assert worker_one.post("/conversation/regenerate", token).status_code == 429
    assert worker_one.limiter.limiter.storage.__class__.__name__ == "RedisStorage"
    assert worker_two.limiter.limiter.storage.__class__.__name__ == "RedisStorage"


def test_blocked_request_precedes_ai_call_and_credit_deduction(fake_server):
    harness = _build_harness(fake_server, hourly="1 per hour")
    token = harness.token("credit-user")

    assert harness.post("/conversation/start", token).status_code == 200
    assert harness.ai_calls["credit-user"] == 1
    assert harness.credit_deductions["credit-user"] == 1

    assert harness.post("/conversation/regenerate", token).status_code == 429
    assert harness.ai_calls["credit-user"] == 1
    assert harness.credit_deductions["credit-user"] == 1


def test_production_requires_shared_redis_configuration(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("RATELIMIT_STORAGE_URI", raising=False)
    with pytest.raises(RuntimeError, match="must be configured"):
        resolve_rate_limit_storage_uri()

    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "memory://")
    with pytest.raises(RuntimeError, match="must use Redis"):
        resolve_rate_limit_storage_uri()

    monkeypatch.setenv("RATELIMIT_STORAGE_URI", "rediss://redis.example/0")
    assert resolve_rate_limit_storage_uri() == "rediss://redis.example/0"


def test_production_fails_startup_when_redis_is_unavailable(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")

    class _Storage:
        @staticmethod
        def check():
            return False

    class _LimiterBackend:
        storage = _Storage()

    class _Limiter:
        limiter = _LimiterBackend()

    with pytest.raises(RuntimeError, match="unavailable"):
        assert_rate_limit_storage_available(_Limiter())
