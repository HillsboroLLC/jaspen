"""Regression coverage for trade-off workspace layout persistence."""

import pytest


@pytest.fixture
def strategy(app):
    from app.routes import strategy as mod

    return mod


def _seed(strategy, user_id, thread_id):
    from app.routes.sessions import save_user_sessions

    save_user_sessions(user_id, {thread_id: {
        "session_id": thread_id,
        "name": "Returns decision",
        "result": {
            "id": "sc_1",
            "jaspen_score": 71,
            "project_name": "Real scorecard",
        },
    }})


def test_the_tradeoff_view_resolves_to_a_carrier(strategy, app):
    uid, tid = "u_tradeoff_1", "thread_t1"
    _seed(strategy, uid, tid)

    kind, _container, _key, carrier = strategy._find_scorecard_carrier(
        uid, tid, "__tradeoff__"
    )

    assert kind == "tradeoff"
    assert isinstance(carrier, dict)
    assert isinstance(carrier.get("result"), dict)


def test_a_missing_thread_still_returns_nothing(strategy, app):
    kind, _container, _key, carrier = strategy._find_scorecard_carrier(
        "u_none", "thread_missing", "__tradeoff__"
    )

    assert kind is None
    assert carrier is None


def test_the_real_scorecard_is_untouched_by_the_sentinel(strategy, app):
    uid, tid = "u_tradeoff_2", "thread_t2"
    _seed(strategy, uid, tid)
    _kind, _container, _key, carrier = strategy._find_scorecard_carrier(
        uid, tid, "__tradeoff__"
    )
    carrier["result"]["display_overrides"] = {
        "section_layout": [{"i": "portfolio"}]
    }

    kind, _container, _key, real = strategy._find_scorecard_carrier(
        uid, tid, "sc_1"
    )

    assert kind == "baseline"
    assert real["result"]["project_name"] == "Real scorecard"
    assert "display_overrides" not in real["result"]


def test_tradeoff_overrides_survive_a_reload(strategy, app):
    from app.routes.sessions import load_user_sessions, save_user_sessions

    uid, tid = "u_tradeoff_3", "thread_t3"
    _seed(strategy, uid, tid)
    _kind, container, key, carrier = strategy._find_scorecard_carrier(
        uid, tid, "__tradeoff__"
    )
    carrier["result"]["display_overrides"] = {
        "section_layout": [{"i": "portfolio", "h": 9}]
    }
    container[key]["tradeoff_view"] = carrier
    save_user_sessions(uid, container)

    reloaded = load_user_sessions(uid)[tid]["tradeoff_view"]["result"][
        "display_overrides"
    ]
    assert reloaded["section_layout"][0]["h"] == 9
