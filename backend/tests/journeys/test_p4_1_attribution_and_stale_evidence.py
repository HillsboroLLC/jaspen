"""P4.1 (re-scoped by OD-1 = C, Nov 19 2026): non-charging integration work.

- D2: a chat turn's ``UsageEvent`` belongs to the member who took the turn
  (the one the legacy meter charged), not to the project owner.
- X1: an unclosed operation is classified, read-only, as a P4.0 turn still
  in progress, stale P4.0 turn evidence, or outstanding. Nothing is closed,
  released or edited.

No charge changes: every balance below is what it was before P4.1, and the
eight strict-xfail financial probes still fail. No provider is called.
"""

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app import db as _db
from app.ai_audit import (
    DEFAULT_MAX_TURN_SECONDS,
    TURN_LIFECYCLE_VERSION,
    UNCLOSED_IN_PROGRESS,
    UNCLOSED_OUTSTANDING,
    UNCLOSED_STALE_TURN_EVIDENCE,
    classify_unclosed_operation,
    operation_is_in_flight,
    report_turn_operations,
)
from app.models import AIOperation, UsageEvent
from tests.journeys.test_conversation_turn_lifecycle import (  # noqa: F401  (fixtures)
    CONTINUE_URL,
    REGENERATE_URL,
    START_URL,
    TURN_TOKENS,
    _TWO_TURNS,
    _add_member,
    _balance,
    _disable_rate_limiting_for_this_file,
    _headers,
    _mk_org,
    _mk_user,
    _post_turn,
    _script_generation,
    _seed,
    _seed_team_thread,
    solo,
)

URLS = {"continue": CONTINUE_URL, "regenerate": REGENERATE_URL}


def _body(route, thread_id, message="Team turn"):
    body = {"thread_id": thread_id}
    if route != "regenerate":
        body["message"] = message
    return body


def _usage_rows(thread_id):
    _db.session.expire_all()
    return UsageEvent.query.filter_by(thread_id=thread_id).order_by(UsageEvent.created_at, UsageEvent.id).all()


def _ops(thread_id):
    _db.session.expire_all()
    return AIOperation.query.filter_by(thread_id=thread_id).all()


@pytest.fixture
def team(app, db, solo):
    owner, org = solo["user"], solo["org"]
    colleague = _mk_user(f"colleague-{uuid.uuid4().hex[:8]}@example.test")
    _add_member(org, colleague)
    return {"owner": owner, "org": org, "colleague": colleague,
            "owner_headers": solo["headers"], "colleague_headers": _headers(app, colleague)}


# --------------------------------------------------------------------------
# D2: shared-project usage is the acting member's
# --------------------------------------------------------------------------

@pytest.mark.parametrize("route", ["continue", "regenerate"])
@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_d2_a_colleagues_turn_is_their_usage_and_their_charge(client, db, team, monkeypatch, route, stream):
    from app.billing_config import effective_plan_key
    from flask import current_app

    _script_generation(monkeypatch)
    owner, colleague, org = team["owner"], team["colleague"], team["org"]
    thread_id = f"t-d2-{route}-{uuid.uuid4().hex[:6]}"
    _seed_team_thread(owner, org, thread_id, history=_TWO_TURNS if route == "regenerate" else None)
    owner_before, colleague_before = _balance(owner), _balance(colleague)

    status, payload = _post_turn(client, URLS[route], team["colleague_headers"], _body(route, thread_id), stream=stream)

    assert status == 200, payload
    [usage] = _usage_rows(thread_id)
    [operation] = _ops(thread_id)
    assert usage.user_id == colleague.id                 # was the owner before D2
    assert usage.organization_id == org.id               # the project's organization
    assert usage.plan_key == effective_plan_key(colleague, current_app.config)
    assert usage.metadata_json["operation_id"] == operation.id
    assert operation.user_id == colleague.id and operation.organization_id == org.id
    # the charge is unchanged by D2: the colleague paid, the owner did not
    assert usage.credits_charged == operation.charged_credits == TURN_TOKENS
    assert _balance(colleague) == colleague_before - TURN_TOKENS
    assert _balance(owner) == owner_before


def test_d2_the_owners_own_turn_stays_the_owners(client, db, team, monkeypatch):
    _script_generation(monkeypatch)
    thread_id = f"t-d2-own-{uuid.uuid4().hex[:6]}"
    _seed_team_thread(team["owner"], team["org"], thread_id)

    status, payload = _post_turn(client, CONTINUE_URL, team["owner_headers"], _body("continue", thread_id), stream=False)

    assert status == 200, payload
    [usage] = _usage_rows(thread_id)
    assert usage.user_id == team["owner"].id


def test_d2_two_members_on_one_project_each_keep_their_own_usage(client, db, team, monkeypatch):
    _script_generation(monkeypatch)
    owner, colleague = team["owner"], team["colleague"]
    thread_id = f"t-d2-both-{uuid.uuid4().hex[:6]}"
    _seed_team_thread(owner, team["org"], thread_id)
    owner_before, colleague_before = _balance(owner), _balance(colleague)

    for headers in (team["owner_headers"], team["colleague_headers"], team["colleague_headers"]):
        status, payload = _post_turn(client, CONTINUE_URL, headers, _body("continue", thread_id), stream=False)
        assert status == 200, payload

    rows = _usage_rows(thread_id)
    assert [row.user_id for row in rows] == [owner.id, colleague.id, colleague.id]
    # each member's usage equals what the meter took from that member
    by_user = {}
    for row in rows:
        by_user[row.user_id] = by_user.get(row.user_id, 0) + int(row.credits_charged or 0)
    assert owner_before - _balance(owner) == by_user[owner.id] == TURN_TOKENS
    assert colleague_before - _balance(colleague) == by_user[colleague.id] == 2 * TURN_TOKENS
    # usage and operations name the same member, turn by turn
    operations = {op.id: op for op in _ops(thread_id)}
    assert all(operations[row.metadata_json["operation_id"]].user_id == row.user_id for row in rows)


@pytest.mark.parametrize("stream", [False, True], ids=["json", "stream"])
def test_d2_a_colleagues_failed_turn_is_recorded_as_theirs_and_charges_no_one(client, db, team, monkeypatch, stream):
    _script_generation(monkeypatch, fail_with=RuntimeError("provider exploded"))
    owner, colleague = team["owner"], team["colleague"]
    thread_id = f"t-d2-fail-{uuid.uuid4().hex[:6]}"
    _seed_team_thread(owner, team["org"], thread_id, history=_TWO_TURNS)
    owner_before, colleague_before = _balance(owner), _balance(colleague)

    target = f"{CONTINUE_URL}?stream=1" if stream else CONTINUE_URL
    response = client.post(target, headers=team["colleague_headers"], json=_body("continue", thread_id))
    response.get_data()

    rows = _usage_rows(thread_id)
    assert rows, "a failed turn still records its (uncharged) usage"
    assert {row.user_id for row in rows} == {colleague.id}
    assert all(int(row.credits_charged or 0) == 0 for row in rows)
    assert _balance(owner) == owner_before
    assert _balance(colleague) == colleague_before


def test_d2_a_replay_by_the_colleague_adds_no_usage_and_keeps_attribution(client, db, team, monkeypatch):
    _script_generation(monkeypatch)
    thread_id = f"t-d2-replay-{uuid.uuid4().hex[:6]}"
    _seed_team_thread(team["owner"], team["org"], thread_id)
    headers = {**team["colleague_headers"], "X-Jaspen-Idempotency-Key": f"key-{uuid.uuid4().hex}"}
    body = _body("continue", thread_id)

    first = client.post(CONTINUE_URL, headers=headers, json=body)
    colleague_after_first = _balance(team["colleague"])
    second = client.post(CONTINUE_URL, headers=headers, json=body)

    assert first.status_code == 200 and second.status_code == 200
    [usage] = _usage_rows(thread_id)
    assert usage.user_id == team["colleague"].id
    assert len(_ops(thread_id)) == 1
    assert _balance(team["colleague"]) == colleague_after_first


def test_d2_an_outsider_is_refused_and_no_usage_is_recorded(client, app, db, team, monkeypatch):
    _script_generation(monkeypatch)
    thread_id = f"t-d2-out-{uuid.uuid4().hex[:6]}"
    _seed_team_thread(team["owner"], team["org"], thread_id, history=_TWO_TURNS)
    outsider = _mk_user(f"outsider-{uuid.uuid4().hex[:8]}@other.test")
    _mk_org(outsider, f"Other{uuid.uuid4().hex[:6]}")

    for url, route in ((CONTINUE_URL, "continue"), (REGENERATE_URL, "regenerate")):
        response = client.post(url, headers=_headers(app, outsider), json=_body(route, thread_id))
        assert response.status_code in {403, 404}

    assert _usage_rows(thread_id) == []
    assert UsageEvent.query.filter_by(user_id=outsider.id).count() == 0
    assert AIOperation.query.filter_by(user_id=outsider.id).count() == 0


def test_d2_a_solo_start_is_unchanged(client, db, solo, monkeypatch):
    _script_generation(monkeypatch)
    status, payload = _post_turn(client, START_URL, solo["headers"], {"message": "New idea"}, stream=False)
    assert status == 200, payload
    thread_id = payload.get("thread_id") or payload.get("session_id")
    [usage] = _usage_rows(thread_id)
    assert usage.user_id == solo["user"].id and usage.organization_id == solo["org"].id


# --------------------------------------------------------------------------
# X1: stale P4.0 evidence versus in-flight operations (read-only)
# --------------------------------------------------------------------------

class _ProcessKilled(BaseException):
    """Stands in for the worker dying mid-turn: nothing in the app catches it."""


def _kill_a_turn(client, user, headers, monkeypatch, thread_id):
    _script_generation(monkeypatch, fail_with=_ProcessKilled())
    _seed(user, thread_id)
    with pytest.raises(_ProcessKilled):
        client.post(CONTINUE_URL, headers=headers, json={"thread_id": thread_id, "message": "Hi"})
    _db.session.rollback()
    [operation] = _ops(thread_id)
    assert operation.status == "started"
    return operation


def _snapshot():
    _db.session.expire_all()
    return sorted(
        (row.id, row.status, row.charged_credits, row.error_code, row.user_id, row.organization_id,
         str(row.metadata_json), row.settled_at)
        for row in AIOperation.query.all()
    )


def _runtime_claim(user, *, age, status="started", operation_type="scorecard_generation", metadata=None):
    """A non-chat operation as ai_runtime claims it (reservation committed with it)."""
    created = datetime.utcnow() - age
    operation = AIOperation(
        id=f"op-{uuid.uuid4().hex}", user_id=user.id, organization_id=user.active_organization_id,
        operation_type=operation_type, status=status, router_mode="legacy", router_version="v",
        policy_mode="legacy", policy_version="v", metadata_json=metadata or {},
        created_at=created, updated_at=created,
    )
    _db.session.add(operation)
    _db.session.commit()
    return operation


def test_x1_a_killed_turn_is_in_progress_then_stale_and_never_changed(client, db, solo, monkeypatch):
    before_balance = _balance(solo["user"])
    operation = _kill_a_turn(client, solo["user"], solo["headers"], monkeypatch, "t-x1-killed")
    before = _snapshot()

    now = datetime.utcnow()
    early = classify_unclosed_operation(operation, now=now)
    assert early["class"] == UNCLOSED_IN_PROGRESS and early["in_flight"] is True
    assert operation_is_in_flight(operation, now=now) is True

    later = now + timedelta(seconds=DEFAULT_MAX_TURN_SECONDS + 60)
    stale = classify_unclosed_operation(operation, now=later)
    assert stale["class"] == UNCLOSED_STALE_TURN_EVIDENCE and stale["in_flight"] is False
    assert stale["reservation_durability"] == "not_recorded"
    assert stale["f3_review"] is True
    assert stale["estimated_reservation"] > 0
    assert operation_is_in_flight(operation, now=later) is False

    # read-only: the row, every other row and the balance are untouched
    assert _snapshot() == before
    assert _balance(solo["user"]) == before_balance


def test_x1_the_bound_is_the_boundary(client, db, solo, monkeypatch):
    operation = _kill_a_turn(client, solo["user"], solo["headers"], monkeypatch, "t-x1-bound")
    at = operation.created_at + timedelta(seconds=600)
    assert classify_unclosed_operation(operation, now=at, max_turn_seconds=601)["class"] == UNCLOSED_IN_PROGRESS
    assert classify_unclosed_operation(operation, now=at, max_turn_seconds=600)["class"] == UNCLOSED_STALE_TURN_EVIDENCE


def test_x1_a_runtime_reservation_is_outstanding_at_any_age(app, db, solo):
    operation = _runtime_claim(solo["user"], age=timedelta(days=90))
    classified = classify_unclosed_operation(operation)
    assert classified["class"] == UNCLOSED_OUTSTANDING and classified["in_flight"] is True
    assert classified["reason"] == "not_a_p4_0_turn_claim"


@pytest.mark.parametrize("variant", [
    "unknown_version", "non_started_status", "bound_to_billing_account", "no_timestamp", "not_conversation",
])
def test_x1_anything_not_recognised_as_p4_0_evidence_fails_closed(variant):
    old = datetime.utcnow() - timedelta(days=5)
    lifecycle = {"version": TURN_LIFECYCLE_VERSION, "claimed_at": old.isoformat()}
    row = dict(id="op-x", status="started", operation_type="conversation", billing_account_id=None,
               created_at=old, metadata_json={"turn_lifecycle": lifecycle})
    if variant == "unknown_version":
        row["metadata_json"] = {"turn_lifecycle": {**lifecycle, "version": "p4.1-s1"}}
    elif variant == "non_started_status":
        row["status"] = "reserved"            # any status P4.1+/Phase 17 may add
    elif variant == "bound_to_billing_account":
        row["billing_account_id"] = "acct-1"
    elif variant == "no_timestamp":
        row["created_at"] = None
        row["metadata_json"] = {"turn_lifecycle": {"version": TURN_LIFECYCLE_VERSION}}
    elif variant == "not_conversation":
        row["operation_type"] = "plan_generation"
    classified = classify_unclosed_operation(SimpleNamespace(**row))
    assert classified["class"] == UNCLOSED_OUTSTANDING
    assert classified["in_flight"] is True


@pytest.mark.parametrize("status", ["succeeded", "degraded", "failed"])
def test_x1_a_closed_operation_is_not_classified(status):
    row = SimpleNamespace(id="op-c", status=status, operation_type="conversation", billing_account_id=None,
                          created_at=datetime.utcnow() - timedelta(days=1), metadata_json={})
    assert classify_unclosed_operation(row) is None
    assert operation_is_in_flight(row) is False


def test_x1_the_report_classifies_every_unclosed_row_and_changes_nothing(client, db, solo, monkeypatch):
    killed = _kill_a_turn(client, solo["user"], solo["headers"], monkeypatch, "t-x1-report")
    runtime = _runtime_claim(solo["user"], age=timedelta(hours=3))
    odd = _runtime_claim(solo["user"], age=timedelta(hours=3), status="reserved", operation_type="conversation",
                         metadata={"turn_lifecycle": {"version": "future"}})
    before = _snapshot()
    before_balance = _balance(solo["user"])

    result = report_turn_operations(now=datetime.utcnow() + timedelta(hours=1))

    by_id = {item["operation_id"]: item for item in result["unclosed"]}
    assert by_id[killed.id]["class"] == UNCLOSED_STALE_TURN_EVIDENCE and by_id[killed.id]["in_flight"] is False
    assert by_id[runtime.id]["class"] == UNCLOSED_OUTSTANDING and by_id[runtime.id]["in_flight"] is True
    # a non-terminal status other than 'started' is reported, not hidden
    assert by_id[odd.id]["class"] == UNCLOSED_OUTSTANDING and by_id[odd.id]["status"] == "reserved"
    assert result["unclosed_by_class"] == {UNCLOSED_IN_PROGRESS: 0, UNCLOSED_STALE_TURN_EVIDENCE: 1,
                                           UNCLOSED_OUTSTANDING: 2}
    assert by_id[killed.id]["usage_rows"] == 0
    assert result["changes_made"] == 0
    assert _snapshot() == before
    assert _balance(solo["user"]) == before_balance


def test_x1_all_history_reaches_rows_older_than_the_default_window(app, db, solo):
    ancient = _runtime_claim(solo["user"], age=timedelta(days=200), operation_type="conversation",
                             metadata={"turn_lifecycle": {"version": TURN_LIFECYCLE_VERSION}})
    windowed = report_turn_operations()
    everything = report_turn_operations(since_days=0)
    assert ancient.id not in {item["operation_id"] for item in windowed["unclosed"]}
    [listed] = [item for item in everything["unclosed"] if item["operation_id"] == ancient.id]
    assert listed["class"] == UNCLOSED_STALE_TURN_EVIDENCE
    assert everything["since"] is None


def test_x1_usage_pointing_at_an_unclosed_turn_is_reported(app, db, solo):
    operation = _runtime_claim(solo["user"], age=timedelta(hours=2), operation_type="conversation",
                               metadata={"turn_lifecycle": {"version": TURN_LIFECYCLE_VERSION}})
    _db.session.add(UsageEvent(
        user_id=solo["user"].id, organization_id=solo["org"].id, thread_id="t-x1-linked",
        endpoint="ai.conversation", operation_type="chat", model_type="pluto", provider="test",
        input_tokens=1, output_tokens=1, total_tokens=2, credits_charged=7, reserved_credits=7,
        settled_credits=7, success=True, metadata_json={"operation_id": operation.id},
    ))
    _db.session.commit()
    [listed] = [item for item in report_turn_operations()["unclosed"] if item["operation_id"] == operation.id]
    assert listed["usage_rows"] == 1 and listed["usage_charged_credits"] == 7


def test_x1_the_report_command_accepts_all_history(app, db):
    outcome = app.test_cli_runner().invoke(args=["ai-operations", "report", "--since-days", "0"])
    assert outcome.exit_code == 0, outcome.output
    assert '"changes_made": 0' in outcome.output and '"unclosed_by_class"' in outcome.output
