"""Rules of the conversation-turn lifecycle (app/conversation_turn.py).

These run against recording fakes, so they state the lifecycle's own
guarantees independently of any billing implementation. A future billing
authority (Phase 12) must keep them green when it replaces the binding.
"""

import pytest

from app.conversation_turn import (
    ConversationTurn,
    TurnBilling,
    TurnLifecycleError,
    TurnStore,
)


class Ledger:
    """A recording stand-in for the financial authority."""

    def __init__(self, *, reserve_ok=True, settle_ok=True, price=40, reserved=100):
        self.calls = []
        self._reserve_ok = reserve_ok
        self._settle_ok = settle_ok
        self._price = price
        self._reserved = reserved

    def port(self):
        return TurnBilling(
            reserve=self.reserve, price=self.price, settle=self.settle,
            release=self.release, persist_balance=self.persist_balance,
            insufficient_payload=self.insufficient_payload,
        )

    def reserve(self, user, model_type, *, token_hint=None):
        self.calls.append(("reserve", model_type, token_hint))
        if not self._reserve_ok:
            return {"ok": False, "reserved": 0, "payload": {"code": "thinking_power_exhausted"}}
        return {"ok": True, "reserved": self._reserved, "payload": None}

    def price(self, usage, model_type, user):
        self.calls.append(("price", model_type))
        return self._price

    def settle(self, user, *, reserved_credits, actual_credits):
        self.calls.append(("settle", reserved_credits, actual_credits))
        if not self._settle_ok:
            return {"ok": False, "charged": reserved_credits, "remaining": 0, "payload": None}
        return {"ok": True, "charged": actual_credits, "remaining": 960, "payload": None}

    def release(self, user, reserved_credits):
        self.calls.append(("release", reserved_credits))

    def persist_balance(self, user_id, remaining):
        self.calls.append(("persist_balance", user_id, remaining))

    def insufficient_payload(self, user, required):
        return {"code": "thinking_power_exhausted", "required": required}

    def names(self):
        return [call[0] for call in self.calls]


def _turn(ledger, *, saved=None, session_key=None, sessions=None):
    saved = saved if saved is not None else []
    session = {"session_id": "t-1", "chat_history": []}

    def save(user_id, all_sessions):
        saved.append((user_id, dict(all_sessions)))
        return True

    return ConversationTurn(
        user=object(), user_id="u-1", thread_id="t-1", session=session,
        sessions=sessions if sessions is not None else {}, model_type="orbit",
        billing=ledger.port(), store=TurnStore(save=save), session_key=session_key,
    )


def test_a_successful_turn_reserves_settles_and_persists_once():
    ledger = Ledger()
    turn = _turn(ledger)

    assert turn.reserve(token_hint=2500) is None
    assert turn.settle({"total_tokens": 40}) is None
    turn.persist_balance()

    assert ledger.calls == [
        ("reserve", "orbit", 2500),
        ("price", "orbit"),
        ("settle", 100, 40),
        ("persist_balance", "u-1", 960),
    ]
    assert (turn.credits_charged, turn.remaining, turn.settled) == (40, 960, True)


def test_a_refused_reservation_returns_the_customer_payload_and_holds_nothing():
    ledger = Ledger(reserve_ok=False)
    turn = _turn(ledger)

    assert turn.reserve() == {"code": "thinking_power_exhausted"}
    assert turn.release_unsettled() is False
    assert ledger.names() == ["reserve"]


def test_a_failed_turn_releases_its_reservation_exactly_once():
    ledger = Ledger()
    turn = _turn(ledger)
    turn.reserve()

    assert turn.release_unsettled() is True
    assert turn.release_unsettled() is False
    assert ledger.calls.count(("release", 100)) == 1


def test_nothing_is_released_after_settlement():
    """A settled charge is undone by reversal, never by handing back the
    reservation, or the customer would be credited twice."""
    ledger = Ledger()
    turn = _turn(ledger)
    turn.reserve()
    turn.settle({})

    assert turn.release_unsettled() is False
    assert "release" not in ledger.names()


def test_a_refused_settlement_is_still_settled_and_never_released():
    ledger = Ledger(settle_ok=False, price=500)
    turn = _turn(ledger)
    turn.reserve()

    assert turn.settle({}) == {"code": "thinking_power_exhausted", "required": 500}
    assert turn.settled is True
    assert turn.release_unsettled() is False


def test_a_pricing_error_leaves_the_turn_unsettled_so_it_can_be_released():
    ledger = Ledger()
    turn = _turn(ledger)
    turn.reserve()

    def boom(*_a, **_k):
        raise RuntimeError("unpriced_provider_model")

    turn._billing = TurnBilling(
        reserve=ledger.reserve, price=boom, settle=ledger.settle, release=ledger.release,
        persist_balance=ledger.persist_balance, insufficient_payload=ledger.insufficient_payload,
    )
    with pytest.raises(RuntimeError):
        turn.settle({})

    assert turn.settled is False
    assert turn.release_unsettled() is True


@pytest.mark.parametrize("step", ["reserve", "settle"])
def test_a_turn_cannot_reserve_or_settle_twice(step):
    turn = _turn(Ledger())
    turn.reserve()
    if step == "settle":
        turn.settle({})
    with pytest.raises(TurnLifecycleError):
        getattr(turn, step)(*([{}] if step == "settle" else []))


def test_the_balance_cannot_be_persisted_before_settlement():
    turn = _turn(Ledger())
    turn.reserve()
    with pytest.raises(TurnLifecycleError):
        turn.persist_balance()


def test_save_writes_only_this_turns_project():
    """Other loaded projects are stale by the time a turn ends. Sending them
    back would revert work saved elsewhere during generation."""
    saved = []
    other = {"session_id": "t-other", "chat_history": ["stale copy"]}
    turn = _turn(Ledger(), saved=saved, session_key="legacy-key", sessions={"t-other": other})

    assert turn.save() is True

    user_id, written = saved[0]
    assert user_id == "u-1"
    assert list(written) == ["legacy-key"]
    assert written["legacy-key"] is turn.session
    # The route's own view still includes this turn's project.
    assert turn.sessions["legacy-key"] is turn.session
