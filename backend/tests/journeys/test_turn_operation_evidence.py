"""P4.0: durable operation evidence for every chat turn (stage S0).

Each chat turn (start, continue, regenerate; JSON and streamed) claims ONE
``AIOperation`` row ('started') committed by itself immediately before it
reserves, and closes that same row at the turn's existing terminal step.

S0 changes no charge. The eight strict-xfail financial probes in
``test_conversation_turn_lifecycle.py`` still fail; balances here are only
asserted to be what they were before P4.0. No provider is called.
"""

import uuid
from datetime import datetime, timedelta

import pytest

from app import db as _db
from app.models import AIOperation, UsageEvent
from tests.journeys.test_conversation_turn_lifecycle import (  # noqa: F401  (fixtures)
    CONTINUE_URL,
    REGENERATE_URL,
    START_URL,
    REPLY,
    TURN_TOKENS,
    _TWO_TURNS,
    _add_member,
    _agent,
    _balance,
    _disable_rate_limiting_for_this_file,
    _headers,
    _mk_org,
    _mk_user,
    _post_turn,
    _script_generation,
    _seed,
    _seed_team_thread,
    _settle_meter,
    _usage,
    solo,
)

URLS = {"start": START_URL, "continue": CONTINUE_URL, "regenerate": REGENERATE_URL}


def _body(route, thread_id, message="Record this turn"):
    body = {"thread_id": thread_id}
    if route != "regenerate":
        body["message"] = message
    return body


def _prepare(user, route, thread_id):
    if route != "start":
        _seed(user, thread_id, history=_TWO_TURNS if route == "regenerate" else None)


def _ops(thread_id):
    _db.session.expire_all()
    return AIOperation.query.filter_by(thread_id=thread_id).all()


def _lifecycle(operation):
    return (operation.metadata_json or {}).get("turn_lifecycle") or {}


def _expected_claim(route):
    """Regenerate reaches its reservation with the legacy meter bootstrap's
    write still uncommitted. The claim never commits that write: on
    PostgreSQL it commits on its own connection, elsewhere it waits for the
    turn's own next commit."""
    if route != "regenerate":
        return True
    return "independent" if _db.engine.dialect.name == "postgresql" else False


def _report(**kwargs):
    from app.ai_audit import report_turn_operations
    return report_turn_operations(**kwargs)


# --------------------------------------------------------------------------
# one logical operation per turn, stable identity, usage linked to it
# --------------------------------------------------------------------------

@pytest.mark.parametrize("route", ["start", "continue", "regenerate"])
@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_every_turn_has_exactly_one_closed_operation_linked_to_its_usage(
    client, db, solo, monkeypatch, route, stream,
):
    _script_generation(monkeypatch)
    thread_id = f"t-op-{route}-{uuid.uuid4().hex[:6]}"
    _prepare(solo["user"], route, thread_id)

    status, payload = _post_turn(client, URLS[route], solo["headers"], _body(route, thread_id), stream=stream)

    assert status == 200, payload
    [operation] = _ops(thread_id)
    [usage] = UsageEvent.query.filter_by(thread_id=thread_id).all()
    lifecycle = _lifecycle(operation)
    assert operation.status == "succeeded"
    assert operation.charged_credits == TURN_TOKENS
    assert operation.user_id == solo["user"].id
    assert operation.organization_id == solo["org"].id
    # usage evidence points at the one operation; operation and usage agree
    assert usage.metadata_json["operation_id"] == operation.id
    assert usage.credits_charged == operation.charged_credits
    assert lifecycle["version"] == "p4.0-s0"
    assert lifecycle["outcome"] == "settled"
    assert lifecycle["claim_committed"] == _expected_claim(route)
    assert lifecycle["streaming"] is stream
    assert lifecycle["route"].endswith(f"conversation_{route}")
    assert lifecycle["reserved_credits"] == lifecycle["estimated_reservation"] > 0
    assert lifecycle["settled_credits"] == TURN_TOKENS
    # observed at close: JSON and regenerate commit the balance before the save
    assert lifecycle.get("balance_committed", False) is (route == "regenerate" or not stream)
    assert lifecycle["generation_commits"] == 0
    assert lifecycle["generation_rollbacks"] == 0
    assert set(lifecycle["cycle_marker"]) == {"user_credits_reset_at", "organization_cycle_reset_at"}
    assert _report()["mismatched"] == []


@pytest.mark.parametrize("route", ["start", "continue", "regenerate"])
def test_the_operation_is_durable_before_the_reservation_is_taken(client, app, db, solo, monkeypatch, route):
    """The claim is committed by itself: a separate connection sees it while
    the turn is reserving, and nothing else was pending when it committed."""
    agent = _agent()
    _script_generation(monkeypatch)
    thread_id = f"t-claim-{route}-{uuid.uuid4().hex[:6]}"
    _prepare(solo["user"], route, thread_id)
    seen = []
    real_reserve = agent._reserve_preflight_credits

    def reserve(*args, **kwargs):
        with _db.engine.connect() as other:
            rows = other.execute(
                AIOperation.__table__.select().where(AIOperation.__table__.c.thread_id == thread_id)
            ).mappings().all()
        seen.append([(row["status"], row["operation_type"]) for row in rows])
        return real_reserve(*args, **kwargs)

    monkeypatch.setattr(agent, "_reserve_preflight_credits", reserve)
    status, payload = _post_turn(client, URLS[route], solo["headers"], _body(route, thread_id), stream=False)

    assert status == 200, payload
    if _expected_claim(route) is False:
        assert seen == [[]]
    else:
        assert seen == [[("started", "conversation")]]
    assert len(_ops(thread_id)) == 1


@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_replay_with_the_same_key_adds_no_operation(client, db, solo, monkeypatch, stream):
    _script_generation(monkeypatch)
    _seed(solo["user"], "t-op-replay")
    headers = {**solo["headers"], "X-Jaspen-Idempotency-Key": f"key-{uuid.uuid4().hex}"}
    body = {"thread_id": "t-op-replay", "message": "Once"}

    first = _post_turn(client, CONTINUE_URL, headers, body, stream=stream)
    balance_after_first = _balance(solo["user"])
    second = _post_turn(client, CONTINUE_URL, headers, body, stream=stream)

    assert first[0] == second[0] == 200
    assert len(_ops("t-op-replay")) == 1
    assert UsageEvent.query.filter_by(thread_id="t-op-replay").count() == 1
    assert _balance(solo["user"]) == balance_after_first


def test_a_concurrent_duplicate_keeps_its_own_row_without_breaking_the_save(app, db, solo):
    """Two in-flight requests with one client key both generate; each turn
    keeps its row and the unique key stays with the first (no IntegrityError)."""
    from app.ai_audit import claim_turn_operation, persist_operation

    user = solo["user"]
    first, _ = claim_turn_operation(user, thread_id="t-dup")
    second, _ = claim_turn_operation(user, thread_id="t-dup")
    for operation_id in (first, second):
        persist_operation(user, usage={**_usage(), "operation_id": operation_id}, charged_credits=TURN_TOKENS,
                          operation_type="framing_clarification", thread_id="t-dup",
                          idempotency_key="same-audit-key")
        _db.session.commit()

    rows = {row.id: row for row in _ops("t-dup")}
    assert set(rows) == {first, second}
    assert rows[first].idempotency_key == "same-audit-key"
    assert rows[second].idempotency_key is None
    assert _lifecycle(rows[second])["concurrent_duplicate_of"] == first
    assert {row.status for row in rows.values()} == {"succeeded"}


# --------------------------------------------------------------------------
# failure, refusal, persistence failure, interruption
# --------------------------------------------------------------------------

@pytest.mark.parametrize("route", ["continue", "regenerate"])
@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_failed_generation_closes_the_operation_as_released(client, db, solo, monkeypatch, route, stream):
    _script_generation(monkeypatch, fail_with=RuntimeError("provider exploded"))
    thread_id = f"t-op-fail-{route}-{uuid.uuid4().hex[:6]}"
    _prepare(solo["user"], route, thread_id)
    before = _balance(solo["user"])

    target = f"{URLS[route]}?stream=1" if stream else URLS[route]
    try:
        client.post(target, headers=solo["headers"], json=_body(route, thread_id)).get_data()
    except RuntimeError:
        pass

    [operation] = _ops(thread_id)
    lifecycle = _lifecycle(operation)
    assert operation.status == "failed"
    assert operation.charged_credits == 0
    assert lifecycle["outcome"] == "generation_failed"
    assert lifecycle["released_credits"] == lifecycle["reserved_credits"] > 0
    assert lifecycle["settled"] is False
    assert _balance(solo["user"]) == before


@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_provider_outage_records_an_unavailable_turn(client, db, solo, monkeypatch, stream):
    agent = _agent()
    _script_generation(monkeypatch, fail_with=agent.ConversationProviderUnavailable("all providers down"))
    _seed(solo["user"], "t-op-outage")

    _post_turn(client, CONTINUE_URL, solo["headers"], {"thread_id": "t-op-outage", "message": "Hi"}, stream=stream)

    [operation] = _ops("t-op-outage")
    assert operation.status == "failed"
    assert _lifecycle(operation)["outcome"] == "provider_unavailable"


@pytest.mark.parametrize("route", ["start", "continue", "regenerate"])
def test_a_refused_reservation_closes_its_operation_and_charges_nothing(client, db, solo, monkeypatch, route):
    agent = _agent()
    calls = []
    _script_generation(monkeypatch, calls=calls)
    monkeypatch.setattr(agent, "_reserve_preflight_credits", lambda *_a, **_k: {
        "ok": False, "required": 10, "reserved": 0, "remaining": 0,
        "payload": {"error": "Out of Thinking Power", "code": "thinking_power_exhausted"},
    })
    thread_id = f"t-op-noreserve-{route}-{uuid.uuid4().hex[:6]}"
    _prepare(solo["user"], route, thread_id)
    before = _balance(solo["user"])

    status, payload = _post_turn(client, URLS[route], solo["headers"], _body(route, thread_id), stream=False)

    assert status == 402
    assert payload == {"error": "Out of Thinking Power", "code": "thinking_power_exhausted"}
    assert calls == []
    [operation] = _ops(thread_id)
    assert operation.status == "failed"
    assert operation.error_code == "thinking_power_exhausted"
    assert _lifecycle(operation)["outcome"] == "refused_at_reserve"
    assert _balance(solo["user"]) == before


@pytest.mark.parametrize("url", [CONTINUE_URL, REGENERATE_URL], ids=["continue", "regenerate"])
def test_reply_not_saved_is_recorded_and_reported_without_changing_the_charge(client, db, solo, monkeypatch, url):
    """F2 evidence: a JSON turn's charge is committed before its save. S0
    records it (and the sweep reports it); it does not refund it."""
    agent = _agent()
    _seed(solo["user"], "t-op-nosave", history=_TWO_TURNS)
    real_save = agent._save_turn_project
    state = {"generated": False}
    monkeypatch.setattr(agent, "_generate_assistant_reply", lambda *a, **k: (
        state.update(generated=True) or (REPLY, _usage(), [], [], None)
    ))

    def failing_save(*args, **kwargs):
        if state["generated"]:
            _db.session.rollback()
            return False
        return real_save(*args, **kwargs)

    monkeypatch.setattr(agent, "_save_turn_project", failing_save)
    before = _balance(solo["user"])
    body = {"thread_id": "t-op-nosave"} if url == REGENERATE_URL else {"thread_id": "t-op-nosave", "message": "More"}

    assert client.post(url, headers=solo["headers"], json=body).status_code == 500

    [operation] = _ops("t-op-nosave")
    lifecycle = _lifecycle(operation)
    assert operation.status == "failed"
    assert operation.error_code == "reply_not_saved"
    assert operation.charged_credits == 0          # no success audit was saved
    assert lifecycle["outcome"] == "reply_not_saved"
    assert lifecycle["balance_committed"] is True
    assert lifecycle["settled_credits"] == TURN_TOKENS
    assert before - _balance(solo["user"]) == TURN_TOKENS   # unchanged F2 behaviour
    [finding] = [item for item in _report()["mismatched"] if item["operation_id"] == operation.id]
    assert "charge_committed_without_saved_reply" in finding["reasons"]


def test_streamed_reply_not_saved_records_that_the_charge_was_not_committed(client, db, solo, monkeypatch):
    agent = _agent()
    _script_generation(monkeypatch)
    _seed(solo["user"], "t-op-nosave2")
    real_save = agent._save_turn_project
    saves = {"n": 0}

    def failing_save(*args, **kwargs):
        saves["n"] += 1
        if saves["n"] >= 2:
            _db.session.rollback()
            return False
        return real_save(*args, **kwargs)

    monkeypatch.setattr(agent, "_save_turn_project", failing_save)
    before = _balance(solo["user"])
    client.post(f"{CONTINUE_URL}?stream=1", headers=solo["headers"], json={
        "thread_id": "t-op-nosave2", "message": "More",
    }).get_data()

    [operation] = _ops("t-op-nosave2")
    assert _lifecycle(operation)["outcome"] == "reply_not_saved"
    assert _lifecycle(operation).get("balance_committed", False) is False
    assert _balance(solo["user"]) == before


@pytest.mark.parametrize("url", [CONTINUE_URL, REGENERATE_URL], ids=["continue", "regenerate"])
def test_a_dropped_stream_is_recorded_as_interrupted(client, db, solo, monkeypatch, url):
    committed = []

    def tool_commits():
        _db.session.commit()
        committed.append(True)

    _script_generation(monkeypatch, during=tool_commits)
    _seed(solo["user"], "t-op-drop", history=_TWO_TURNS)
    body = {"thread_id": "t-op-drop"} if url == REGENERATE_URL else {"thread_id": "t-op-drop", "message": "More"}

    response = client.post(f"{url}?stream=1", headers=solo["headers"], json=body, buffered=False)
    chunks = iter(response.response)
    while not committed:
        next(chunks)
    response.close()

    [operation] = _ops("t-op-drop")
    lifecycle = _lifecycle(operation)
    assert operation.status == "failed"
    assert operation.error_code == "client_disconnected"
    assert lifecycle["outcome"] == "interrupted"
    assert lifecycle["generation_commits"] == 1
    [finding] = [item for item in _report()["mismatched"] if item["operation_id"] == operation.id]
    assert "reservation_possibly_kept_by_mid_turn_commit" in finding["reasons"]   # F3


@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_a_rollback_inside_generation_is_recorded(client, db, solo, monkeypatch, stream):
    _script_generation(monkeypatch, during=_db.session.rollback)
    _seed(solo["user"], "t-op-rb")

    status, payload = _post_turn(client, CONTINUE_URL, solo["headers"],
                                 {"thread_id": "t-op-rb", "message": "Bid?"}, stream=stream)

    assert status == 200, payload
    [operation] = _ops("t-op-rb")
    assert _lifecycle(operation)["generation_rollbacks"] == 1
    [finding] = [item for item in _report()["mismatched"] if item["operation_id"] == operation.id]
    assert "reservation_possibly_discarded_by_rollback" in finding["reasons"]   # F4


class _ProcessKilled(BaseException):
    """Stands in for the worker dying mid-turn: nothing in the app catches it."""


def test_a_killed_turn_leaves_one_started_row_that_the_report_lists(client, db, solo, monkeypatch):
    _script_generation(monkeypatch, fail_with=_ProcessKilled())
    _seed(solo["user"], "t-op-killed")
    before = _balance(solo["user"])

    with pytest.raises(_ProcessKilled):
        client.post(CONTINUE_URL, headers=solo["headers"], json={"thread_id": "t-op-killed", "message": "Hi"})

    [operation] = _ops("t-op-killed")
    assert operation.status == "started"
    assert _balance(solo["user"]) == before
    assert operation.id not in {item["operation_id"] for item in _report()["unclosed"]}  # not stale yet
    later = datetime.utcnow() + timedelta(minutes=31)
    [listed] = [item for item in _report(now=later)["unclosed"] if item["operation_id"] == operation.id]
    assert listed["conversation_turn"] is True
    assert listed["estimated_reservation"] > 0


def test_the_report_changes_nothing(client, db, solo, monkeypatch):
    _script_generation(monkeypatch, fail_with=_ProcessKilled())
    _seed(solo["user"], "t-op-report")
    with pytest.raises(_ProcessKilled):
        client.post(CONTINUE_URL, headers=solo["headers"], json={"thread_id": "t-op-report", "message": "Hi"})
    _db.session.rollback()

    def snapshot():
        _db.session.expire_all()
        return sorted(
            (row.id, row.status, row.charged_credits, row.error_code, str(row.metadata_json))
            for row in AIOperation.query.all()
        ), _balance(solo["user"])

    before = snapshot()
    result = _report(now=datetime.utcnow() + timedelta(hours=2))
    assert result["changes_made"] == 0 and result["unclosed"]
    assert snapshot() == before


def test_the_report_command_runs(app, db):
    runner = app.test_cli_runner()
    outcome = runner.invoke(args=["ai-operations", "report", "--older-than-minutes", "30"])
    assert outcome.exit_code == 0, outcome.output
    assert '"changes_made": 0' in outcome.output


# --------------------------------------------------------------------------
# state transitions
# --------------------------------------------------------------------------

def test_transition_rules():
    from app.ai_audit import OperationTransitionError, check_operation_transition

    for target in ("succeeded", "degraded", "failed"):
        check_operation_transition("started", target)
        check_operation_transition(target, target)       # idempotent re-close
    for current, target in [("succeeded", "failed"), ("failed", "succeeded"),
                            ("degraded", "succeeded"), ("succeeded", "started"), ("started", "started")]:
        with pytest.raises(OperationTransitionError):
            check_operation_transition(current, target)


def test_a_closed_turn_operation_cannot_be_reclosed_differently(app, db, solo):
    from app.ai_audit import OperationTransitionError, claim_turn_operation, persist_operation

    user = solo["user"]
    operation_id, _ = claim_turn_operation(user, thread_id="t-reclose")
    persist_operation(user, usage={**_usage(), "operation_id": operation_id}, charged_credits=TURN_TOKENS,
                      operation_type="framing_clarification", thread_id="t-reclose")
    _db.session.commit()

    with pytest.raises(OperationTransitionError):
        persist_operation(user, usage={**_usage(), "operation_id": operation_id, "operation_failed": True},
                          charged_credits=0, thread_id="t-reclose", success=False)
    _db.session.rollback()
    [operation] = _ops("t-reclose")
    assert (operation.status, operation.charged_credits) == ("succeeded", TURN_TOKENS)


def test_a_late_close_keeps_the_terminal_status_and_adds_what_happened(app, db, solo):
    from app.ai_audit import claim_turn_operation, close_turn_operation_alone, persist_operation

    user = solo["user"]
    operation_id, _ = claim_turn_operation(user, thread_id="t-late")
    persist_operation(user, usage={**_usage(), "operation_id": operation_id}, charged_credits=TURN_TOKENS,
                      operation_type="framing_clarification", thread_id="t-late")
    _db.session.commit()

    close_turn_operation_alone(operation_id, outcome="replay_cache_not_saved")

    [operation] = _ops("t-late")
    assert operation.status == "succeeded"
    assert _lifecycle(operation)["after_close"] == [{"event": "replay_cache_not_saved"}]


def test_a_claim_never_commits_someone_elses_pending_write(app, db, solo):
    from app.ai_audit import claim_turn_operation

    user = solo["user"]
    original_name = user.name
    user.name = "Pending, uncommitted"
    operation_id, claim = claim_turn_operation(user, thread_id="t-dirty")
    postgres = _db.engine.dialect.name == "postgresql"
    assert claim["claim_committed"] == ("independent" if postgres else False)
    _db.session.rollback()     # the request ends without committing

    _db.session.expire_all()
    assert user.name == original_name          # the pending write was never committed
    operation = _db.session.get(AIOperation, operation_id)
    if postgres:
        # committed on its own connection: durable, and alone
        assert operation is not None and operation.status == "started"
    else:
        # deferred to the turn's own commit, so it went with the rollback
        assert operation is None


# --------------------------------------------------------------------------
# tenant and project isolation
# --------------------------------------------------------------------------

@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_a_colleagues_turn_is_their_operation_on_the_organizations_project(client, app, db, solo, monkeypatch, stream):
    _script_generation(monkeypatch)
    owner, org = solo["user"], solo["org"]
    colleague = _mk_user(f"colleague-{uuid.uuid4().hex[:8]}@example.test")
    _add_member(org, colleague)
    _settle_meter(colleague)
    thread_id = f"t-op-team-{uuid.uuid4().hex[:6]}"
    _seed_team_thread(owner, org, thread_id)

    status, payload = _post_turn(client, CONTINUE_URL, _headers(app, colleague),
                                 {"thread_id": thread_id, "message": "Mine"}, stream=stream)

    assert status == 200, payload
    [operation] = _ops(thread_id)
    # The operation is the acting member's. (Its UsageEvent is too since
    # P4.1 D2; see test_p4_1_attribution_and_stale_evidence.py.)
    assert operation.user_id == colleague.id
    assert operation.organization_id == org.id
    assert _lifecycle(operation)["project_organization_id"] == org.id


@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_refused_access_creates_no_operation(client, app, db, solo, monkeypatch, stream):
    _script_generation(monkeypatch)
    _seed(solo["user"], "t-op-private", history=_TWO_TURNS)
    outsider = _mk_user(f"outsider-{uuid.uuid4().hex[:8]}@other.test")
    _mk_org(outsider, f"Other{uuid.uuid4().hex[:6]}")
    _settle_meter(outsider)

    for url, body in ((CONTINUE_URL, {"thread_id": "t-op-private", "message": "Hi"}),
                      (REGENERATE_URL, {"thread_id": "t-op-private"})):
        target = f"{url}?stream=1" if stream else url
        response = client.post(target, headers=_headers(app, outsider), json=body)
        response.get_data()
        assert response.status_code in {403, 404}

    assert AIOperation.query.filter_by(user_id=outsider.id).count() == 0


# --------------------------------------------------------------------------
# C1 (independent audit): an unhandled exception in a JSON finish path
# --------------------------------------------------------------------------

def _raise_on_reply(monkeypatch, name, *, error=RuntimeError("artifact step exploded")):
    """Make ``name`` raise only when it handles this turn's scripted reply,
    so loading and seeding the project is untouched."""
    agent = _agent()
    real = getattr(agent, name)

    def boom(*args, **kwargs):
        if REPLY in args or kwargs.get("reply") == REPLY:
            raise error
        return real(*args, **kwargs)

    monkeypatch.setattr(agent, name, boom)


def _post_json_expecting_500(client, url, headers, body):
    try:
        response = client.post(url, headers=headers, json=body)
    except RuntimeError:
        return None  # PROPAGATE_EXCEPTIONS in some configurations
    return response.status_code


@pytest.mark.parametrize("route,raising", [
    ("start", "_artifact_entries_from_actions"),
    ("continue", "_artifact_entries_from_actions"),
    ("regenerate", "_assistant_chat_entry"),
])
def test_c1_charged_turn_that_fails_before_its_save_is_classified_f2(client, db, solo, monkeypatch, route, raising):
    """The audit's reproduction: the JSON charge (120) is committed, then the
    turn raises before its reply is saved. Before C1 the row stayed 'started'
    with no outcome and was reported as a possibly held reservation."""
    _script_generation(monkeypatch)
    _raise_on_reply(monkeypatch, raising)
    thread_id = f"t-c1-{route}-{uuid.uuid4().hex[:6]}"
    _prepare(solo["user"], route, thread_id)
    before = _balance(solo["user"])
    key = f"key-c1-{uuid.uuid4().hex}"

    status = _post_json_expecting_500(client, URLS[route], {**solo["headers"], "X-Jaspen-Idempotency-Key": key},
                                      _body(route, thread_id))

    assert status in (500, None)
    assert before - _balance(solo["user"]) == TURN_TOKENS == 120   # charge unchanged (F2 kept)
    [operation] = _ops(thread_id)
    lifecycle = _lifecycle(operation)
    assert operation.status == "failed"
    assert operation.error_code == "RuntimeError"
    assert operation.charged_credits == 0
    assert lifecycle["outcome"] == "failed_unexpectedly"
    assert lifecycle["settled"] is True
    assert lifecycle["balance_committed"] is True
    assert lifecycle["settled_credits"] == TURN_TOKENS
    assert lifecycle["closed_alone"] is True
    assert lifecycle["client_idempotency_key"] == key
    assert UsageEvent.query.filter_by(thread_id=thread_id).count() == 0   # as before: no usage row
    [finding] = [item for item in _report()["mismatched"] if item["operation_id"] == operation.id]
    assert "charge_committed_without_saved_reply" in finding["reasons"]
    later = datetime.utcnow() + timedelta(minutes=31)
    assert operation.id not in {item["operation_id"] for item in _report(now=later)["unclosed"]}


@pytest.mark.parametrize("route", ["start", "continue"])
def test_c1_failure_before_settlement_is_unsettled_and_charges_nothing(client, db, solo, monkeypatch, route):
    _script_generation(monkeypatch)
    _raise_on_reply(monkeypatch, "_apply_scoring_failure_state")
    thread_id = f"t-c1-pre-{route}-{uuid.uuid4().hex[:6]}"
    _prepare(solo["user"], route, thread_id)
    before = _balance(solo["user"])

    assert _post_json_expecting_500(client, URLS[route], solo["headers"], _body(route, thread_id)) in (500, None)

    assert _balance(solo["user"]) == before
    [operation] = _ops(thread_id)
    lifecycle = _lifecycle(operation)
    assert operation.status == "failed"
    assert lifecycle["outcome"] == "failed_unexpectedly"
    assert lifecycle["settled"] is False
    assert "balance_committed" not in lifecycle
    finding = [item for item in _report()["mismatched"] if item["operation_id"] == operation.id]
    assert not finding or "charge_committed_without_saved_reply" not in finding[0]["reasons"]


@pytest.mark.parametrize("route", ["continue", "regenerate"])
def test_c1_settled_but_not_yet_durable_is_not_reported_as_a_charge(client, db, solo, monkeypatch, route):
    """Settled in memory, then the balance write itself fails: nothing was
    committed, the teardown discards the settlement, so this is not F2."""
    agent = _agent()
    _script_generation(monkeypatch)

    def persist_fails(*_a, **_k):
        raise RuntimeError("balance write failed")

    monkeypatch.setattr(agent, "_persist_credit_deduction", persist_fails)
    thread_id = f"t-c1-mid-{route}-{uuid.uuid4().hex[:6]}"
    _prepare(solo["user"], route, thread_id)
    before = _balance(solo["user"])

    assert _post_json_expecting_500(client, URLS[route], solo["headers"], _body(route, thread_id)) in (500, None)

    assert _balance(solo["user"]) == before
    [operation] = _ops(thread_id)
    lifecycle = _lifecycle(operation)
    assert lifecycle["outcome"] == "failed_unexpectedly"
    assert lifecycle["settled"] is True
    assert "balance_committed" not in lifecycle
    finding = [item for item in _report()["mismatched"] if item["operation_id"] == operation.id]
    assert not finding or "charge_committed_without_saved_reply" not in finding[0]["reasons"]


def test_c1_failure_after_the_reply_was_saved_keeps_the_settled_close(client, db, solo, monkeypatch):
    agent = _agent()
    _script_generation(monkeypatch)
    real_save = agent._save_turn_project
    saved = {"n": 0}

    def counting_save(*args, **kwargs):
        result = real_save(*args, **kwargs)
        saved["n"] += 1
        return result

    real_payload = agent._public_usage_payload

    def payload_fails(*args, **kwargs):
        if saved["n"]:
            raise RuntimeError("payload exploded")
        return real_payload(*args, **kwargs)

    monkeypatch.setattr(agent, "_save_turn_project", counting_save)
    monkeypatch.setattr(agent, "_public_usage_payload", payload_fails)
    _seed(solo["user"], "t-c1-post")
    before = _balance(solo["user"])

    assert _post_json_expecting_500(client, CONTINUE_URL, solo["headers"],
                                    {"thread_id": "t-c1-post", "message": "Hi"}) in (500, None)

    assert before - _balance(solo["user"]) == TURN_TOKENS
    [operation] = _ops("t-c1-post")
    lifecycle = _lifecycle(operation)
    assert operation.status == "succeeded"           # the reply and its charge were saved
    assert operation.charged_credits == TURN_TOKENS
    assert lifecycle["outcome"] == "settled"
    assert [event["event"] for event in lifecycle["after_close"]] == ["failed_unexpectedly"]
    finding = [item for item in _report()["mismatched"] if item["operation_id"] == operation.id]
    assert not finding


# --------------------------------------------------------------------------
# C2 (independent audit): the client's actual idempotency key is kept
# --------------------------------------------------------------------------

def _keyed(headers, key):
    return {**headers, "X-Jaspen-Idempotency-Key": key}


@pytest.mark.parametrize("route", ["start", "continue", "regenerate"])
@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_c2_a_successful_turn_keeps_its_key_and_the_audit_key_is_unchanged(client, db, solo, monkeypatch, route, stream):
    import hashlib

    _script_generation(monkeypatch)
    thread_id = f"t-c2-ok-{route}-{uuid.uuid4().hex[:6]}"
    _prepare(solo["user"], route, thread_id)
    key = f"key-c2-{uuid.uuid4().hex}"

    status, payload = _post_turn(client, URLS[route], _keyed(solo["headers"], key), _body(route, thread_id), stream=stream)

    assert status == 200, payload
    [operation] = _ops(thread_id)
    lifecycle = _lifecycle(operation)
    assert lifecycle["client_idempotency_key"] == key        # survives persist_operation's close
    assert lifecycle["client_idempotency_key_present"] is True
    # the existing hashed billing/audit key is untouched
    assert operation.idempotency_key == hashlib.sha256(f"{operation.operation_type}:{key}".encode()).hexdigest()


def test_c2_no_key_is_recorded_as_none(client, db, solo, monkeypatch):
    _script_generation(monkeypatch)
    _seed(solo["user"], "t-c2-none")
    _post_turn(client, CONTINUE_URL, solo["headers"], {"thread_id": "t-c2-none", "message": "Hi"}, stream=False)
    [operation] = _ops("t-c2-none")
    assert _lifecycle(operation)["client_idempotency_key"] is None
    assert _lifecycle(operation)["client_idempotency_key_present"] is False
    assert operation.idempotency_key is None


@pytest.mark.parametrize("route", ["start", "continue", "regenerate"])
def test_c2_a_refused_turn_carries_its_key(client, db, solo, monkeypatch, route):
    agent = _agent()
    _script_generation(monkeypatch)
    monkeypatch.setattr(agent, "_reserve_preflight_credits", lambda *_a, **_k: {
        "ok": False, "required": 10, "reserved": 0, "remaining": 0,
        "payload": {"error": "Out of Thinking Power", "code": "thinking_power_exhausted"},
    })
    thread_id = f"t-c2-ref-{route}-{uuid.uuid4().hex[:6]}"
    _prepare(solo["user"], route, thread_id)
    key = f"key-c2-{uuid.uuid4().hex}"

    status, _ = _post_turn(client, URLS[route], _keyed(solo["headers"], key), _body(route, thread_id), stream=False)

    assert status == 402
    [operation] = _ops(thread_id)
    assert _lifecycle(operation)["outcome"] == "refused_at_reserve"
    assert _lifecycle(operation)["client_idempotency_key"] == key


@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_c2_a_failed_turn_carries_its_key(client, db, solo, monkeypatch, stream):
    _script_generation(monkeypatch, fail_with=RuntimeError("provider exploded"))
    _seed(solo["user"], "t-c2-fail")
    key = f"key-c2-{uuid.uuid4().hex}"
    target = f"{CONTINUE_URL}?stream=1" if stream else CONTINUE_URL
    try:
        client.post(target, headers=_keyed(solo["headers"], key),
                    json={"thread_id": "t-c2-fail", "message": "Hi"}).get_data()
    except RuntimeError:
        pass

    [operation] = _ops("t-c2-fail")
    assert _lifecycle(operation)["outcome"] == "generation_failed"
    assert _lifecycle(operation)["client_idempotency_key"] == key


def test_c2_an_interrupted_stream_carries_its_key(client, db, solo, monkeypatch):
    committed = []

    def tool_commits():
        _db.session.commit()
        committed.append(True)

    _script_generation(monkeypatch, during=tool_commits)
    _seed(solo["user"], "t-c2-drop")
    key = f"key-c2-{uuid.uuid4().hex}"
    response = client.post(f"{CONTINUE_URL}?stream=1", headers=_keyed(solo["headers"], key),
                           json={"thread_id": "t-c2-drop", "message": "Hi"}, buffered=False)
    chunks = iter(response.response)
    while not committed:
        next(chunks)
    response.close()

    [operation] = _ops("t-c2-drop")
    assert _lifecycle(operation)["outcome"] == "interrupted"
    assert _lifecycle(operation)["client_idempotency_key"] == key


def test_c2_retry_after_a_refusal_is_a_new_operation_with_the_same_key(client, db, solo, monkeypatch):
    """Retry semantics are unchanged: a refused turn has no replay payload, so
    its retry runs as a new turn. Both rows now share the key, which is what
    P4.1 needs to tie them together."""
    agent = _agent()
    _script_generation(monkeypatch)
    real_reserve = agent._reserve_preflight_credits
    attempts = {"n": 0}

    def refuse_first(*args, **kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            return {"ok": False, "required": 10, "reserved": 0, "remaining": 0,
                    "payload": {"error": "Out of Thinking Power", "code": "thinking_power_exhausted"}}
        return real_reserve(*args, **kwargs)

    monkeypatch.setattr(agent, "_reserve_preflight_credits", refuse_first)
    _seed(solo["user"], "t-c2-retry")
    key = f"key-c2-{uuid.uuid4().hex}"
    body = {"thread_id": "t-c2-retry", "message": "Hi"}
    before = _balance(solo["user"])

    assert _post_turn(client, CONTINUE_URL, _keyed(solo["headers"], key), body, stream=False)[0] == 402
    assert _post_turn(client, CONTINUE_URL, _keyed(solo["headers"], key), body, stream=False)[0] == 200
    assert _post_turn(client, CONTINUE_URL, _keyed(solo["headers"], key), body, stream=False)[0] == 200  # replay

    rows = sorted(_ops("t-c2-retry"), key=lambda row: row.created_at)
    assert [_lifecycle(row)["outcome"] for row in rows] == ["refused_at_reserve", "settled"]
    assert {_lifecycle(row)["client_idempotency_key"] for row in rows} == {key}
    assert len({row.id for row in rows}) == 2
    assert before - _balance(solo["user"]) == TURN_TOKENS    # charged once
    assert UsageEvent.query.filter_by(thread_id="t-c2-retry").count() == 1


def test_c2_the_same_key_from_two_customers_stays_separate(client, app, db, solo, monkeypatch):
    _script_generation(monkeypatch)
    other = _mk_user(f"other-{uuid.uuid4().hex[:8]}@example.test")
    other_org = _mk_org(other, f"Other{uuid.uuid4().hex[:6]}")
    _settle_meter(other)
    key = f"key-c2-{uuid.uuid4().hex}"
    _seed(solo["user"], "t-c2-a")
    _seed(other, "t-c2-b")
    before = (_balance(solo["user"]), _balance(other))

    assert _post_turn(client, CONTINUE_URL, _keyed(solo["headers"], key),
                      {"thread_id": "t-c2-a", "message": "Hi"}, stream=False)[0] == 200
    assert _post_turn(client, CONTINUE_URL, _keyed(_headers(app, other), key),
                      {"thread_id": "t-c2-b", "message": "Hi"}, stream=False)[0] == 200

    [mine] = _ops("t-c2-a")
    [theirs] = _ops("t-c2-b")
    assert mine.id != theirs.id
    assert (mine.user_id, mine.organization_id) == (solo["user"].id, solo["org"].id)
    assert (theirs.user_id, theirs.organization_id) == (other.id, other_org.id)
    assert _lifecycle(mine)["client_idempotency_key"] == _lifecycle(theirs)["client_idempotency_key"] == key
    assert (before[0] - _balance(solo["user"]), before[1] - _balance(other)) == (TURN_TOKENS, TURN_TOKENS)


def test_c2_an_over_long_key_is_still_refused_before_any_operation(client, db, solo, monkeypatch):
    _script_generation(monkeypatch)
    _seed(solo["user"], "t-c2-long")
    status, _ = _post_turn(client, CONTINUE_URL, _keyed(solo["headers"], "k" * 201),
                           {"thread_id": "t-c2-long", "message": "Hi"}, stream=False)
    assert status == 409   # the route's existing refusal, unchanged
    assert _ops("t-c2-long") == []


def test_c2_claim_bounds_the_stored_key(app, db, solo):
    from app.ai_audit import claim_turn_operation
    _, lifecycle = claim_turn_operation(solo["user"], thread_id="t-c2-bound",
                                        client_idempotency_key="  " + "k" * 250 + "  ")
    assert lifecycle["client_idempotency_key"] == "k" * 200


# --------------------------------------------------------------------------
# R1 (re-acceptance): the observed balance commit is the only F2 signal
# --------------------------------------------------------------------------

def _balance_write_returns_without_commit(monkeypatch):
    """Drive the REAL legacy helper down one of its silent no-commit returns
    (``remaining is None``): it returns normally and commits nothing, as it
    does when its user re-read fails or the user is missing."""
    agent = _agent()
    real = agent._persist_credit_deduction
    monkeypatch.setattr(agent, "_persist_credit_deduction", lambda user_id, _remaining: real(user_id, None))


def _fail_saves_after_generation(monkeypatch):
    agent = _agent()
    real_save = agent._save_turn_project
    state = {"generated": False}

    def failing_save(*args, **kwargs):
        if state["generated"]:
            _db.session.rollback()
            return False
        return real_save(*args, **kwargs)

    monkeypatch.setattr(agent, "_save_turn_project", failing_save)
    return state


@pytest.mark.parametrize("route", ["start", "continue", "regenerate"])
@pytest.mark.parametrize("balance_write", ["silently_uncommitted", "committed"])
def test_r1_reply_not_saved_reports_f2_only_when_the_charge_was_durable(
    client, db, solo, monkeypatch, route, balance_write,
):
    """The exact R1 case: the balance write returns without committing, then
    the reply save fails. Before R1 the hard-coded flag reported F2 on a turn
    that charged nothing. The 'committed' control is the genuine F2."""
    state = _fail_saves_after_generation(monkeypatch)
    _script_generation(monkeypatch, during=lambda: state.update(generated=True))
    if balance_write == "silently_uncommitted":
        _balance_write_returns_without_commit(monkeypatch)
    thread_id = f"t-r1-{route}-{uuid.uuid4().hex[:6]}"
    _prepare(solo["user"], route, thread_id)
    before = _balance(solo["user"])

    status, _ = _post_turn(client, URLS[route], solo["headers"], _body(route, thread_id), stream=False)

    assert status == 500
    [operation] = _ops(thread_id)
    lifecycle = _lifecycle(operation)
    assert operation.status == "failed"
    assert lifecycle["outcome"] == "reply_not_saved"
    assert lifecycle["settled_credits"] == TURN_TOKENS
    finding = [item for item in _report()["mismatched"] if item["operation_id"] == operation.id]
    reasons = finding[0]["reasons"] if finding else []
    if balance_write == "committed":
        assert before - _balance(solo["user"]) == TURN_TOKENS
        assert lifecycle["balance_committed"] is True
        assert "charge_committed_without_saved_reply" in reasons
    else:
        assert _balance(solo["user"]) == before
        assert "balance_committed" not in lifecycle
        assert "charge_committed_without_saved_reply" not in reasons


@pytest.mark.parametrize("route,raising", [
    ("start", "_artifact_entries_from_actions"),
    ("continue", "_artifact_entries_from_actions"),
    ("regenerate", "_assistant_chat_entry"),
])
def test_r1_uncommitted_balance_then_an_unexpected_error_is_not_f2(client, db, solo, monkeypatch, route, raising):
    """The real swallowed balance failure (no injected raise), followed by an
    unhandled error before the save: charged nothing, so no F2."""
    _script_generation(monkeypatch)
    _balance_write_returns_without_commit(monkeypatch)
    _raise_on_reply(monkeypatch, raising)
    thread_id = f"t-r1-exc-{route}-{uuid.uuid4().hex[:6]}"
    _prepare(solo["user"], route, thread_id)
    before = _balance(solo["user"])

    assert _post_json_expecting_500(client, URLS[route], solo["headers"], _body(route, thread_id)) in (500, None)

    assert _balance(solo["user"]) == before
    [operation] = _ops(thread_id)
    lifecycle = _lifecycle(operation)
    assert lifecycle["outcome"] == "failed_unexpectedly"
    assert lifecycle["settled"] is True
    assert "balance_committed" not in lifecycle
    finding = [item for item in _report()["mismatched"] if item["operation_id"] == operation.id]
    assert not finding or "charge_committed_without_saved_reply" not in finding[0]["reasons"]
