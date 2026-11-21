"""P4.0 hard rule: no commit is added between a turn's reservation and its
terminal step.

Adding one would make the reservation durable mid-turn, which is the S1
(F2-F4 correction) behaviour and changes live charging. This file uses only
route-level seams, so it runs unchanged on the pre-P4.0 baseline; the
expected numbers are the baseline's.

Window: from the moment the reservation returns until the turn's first
project save is attempted (the save is the terminal commit for a turn that
reaches it). ``persist_balance`` is the only commit allowed in that window,
and only on the paths that already commit the charge before saving.
"""

import uuid

import pytest
from sqlalchemy import event
from sqlalchemy.orm import Session

from app import db as _db
from tests.journeys.test_conversation_turn_lifecycle import (  # noqa: F401  (fixtures)
    CONTINUE_URL,
    REGENERATE_URL,
    START_URL,
    _TWO_TURNS,
    _agent,
    _disable_rate_limiting_for_this_file,
    _post_turn,
    _script_generation,
    _seed,
    solo,
)

URLS = {"start": START_URL, "continue": CONTINUE_URL, "regenerate": REGENERATE_URL}

# (route, streamed) -> commits in the window on the baseline.
EXPECTED = {
    ("start", False): 1, ("start", True): 0,
    ("continue", False): 1, ("continue", True): 0,
    ("regenerate", False): 1, ("regenerate", True): 1,
}


@pytest.mark.parametrize("route", ["start", "continue", "regenerate"])
@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_no_commit_is_added_between_reserve_and_the_terminal_step(client, db, solo, monkeypatch, route, stream):
    agent = _agent()
    _script_generation(monkeypatch)
    thread_id = f"t-window-{route}-{uuid.uuid4().hex[:6]}"
    if route != "start":
        _seed(solo["user"], thread_id, history=_TWO_TURNS if route == "regenerate" else None)

    window = {"open": False, "closed": False, "commits": 0}
    real_reserve = agent._reserve_preflight_credits
    real_save = agent._save_turn_project

    def reserve(*args, **kwargs):
        result = real_reserve(*args, **kwargs)
        window["open"] = True
        return result

    def save(*args, **kwargs):
        if window["open"]:
            window["open"], window["closed"] = False, True
        return real_save(*args, **kwargs)

    def count(_session):
        if window["open"]:
            window["commits"] += 1

    monkeypatch.setattr(agent, "_reserve_preflight_credits", reserve)
    monkeypatch.setattr(agent, "_save_turn_project", save)
    event.listen(Session, "after_commit", count)
    try:
        body = {"thread_id": thread_id}
        if route != "regenerate":
            body["message"] = "Window"
        status, payload = _post_turn(client, URLS[route], solo["headers"], body, stream=stream)
    finally:
        event.remove(Session, "after_commit", count)

    assert status == 200, payload
    assert window["closed"]
    assert window["commits"] == EXPECTED[(route, stream)]
