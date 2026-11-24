"""BI-1: Phase 14 classifies unclosed legacy operations, and reviewers record decisions (D-1, D-3).

The P4.1 X1 classifier (``ai_audit.classify_unclosed_operation``) feeds Phase
14, which refines it into in flight, unrecognized, already charged, stale turn
evidence, and outstanding reservation. Only the last two take a recorded,
individually reviewed decision, and only ``no_compensation_owed`` lets the
account proceed: nothing is compensated, no legacy row is written, and with no
configured age limit every unclosed operation still blocks (fail closed).

ORM tests run on SQLite (or an isolated PostgreSQL schema). The ``PG`` tests
run on the fully migrated PostgreSQL database, with every guard live.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
import threading
import uuid

import pytest
import sqlalchemy as sa
from flask import current_app

import app.billing_migration as bm
import app.billing_rehearsal as br
from app.ai_audit import TURN_LIFECYCLE_VERSION
from app.billing_migration import (
    MigrationConflictError,
    MigrationError,
    MigrationPermissionError,
    plan_account_backfill,
    record_operation_decision,
    unclosed_operation_review,
)
from app.models import AIOperation, BillingAccount, OrganizationMember, User
from app.models_billing_phase14 import BillingMigrationOperationDecision
from tests.test_billing_migration import (
    PG,
    _migrated_engine,
    _ops,
    backfill,
    codes,
    entries,
    grant,
    legacy_snapshot,
    migrated,
    naive,
    now,
    organization,
    payment,
    personal,
    reviewer,
    user,
)

KEY = bm.MAX_TURN_SECONDS_CONFIG_KEY
BOUND = 1800
REVISION = "c8a9989843b5"
TABLE = "billing_migration_operation_decisions"


@pytest.fixture
def bound(monkeypatch):
    monkeypatch.setitem(current_app.config, KEY, BOUND)
    return BOUND


def turn(session, ns, *, age=timedelta(hours=2), lifecycle=None, status="started", account=None):
    """A P4.0 chat-turn operation claimed ``age`` ago (no outcome unless ``lifecycle`` says so)."""
    facts = {"version": TURN_LIFECYCLE_VERSION, "estimated_reservation": 4000, "cycle_marker": {},
             "claimed_at": naive(now(session) - age).isoformat(), "claim_committed": True, "outcome": None}
    facts.update(lifecycle or {})
    row = AIOperation(id=str(uuid.uuid4()), user_id=ns.user, organization_id=ns.org, status=status,
                      operation_type="conversation", router_version="test", policy_version="test",
                      billing_account_id=account, metadata_json={"turn_lifecycle": facts},
                      created_at=naive(now(session) - age), updated_at=naive(now(session) - age))
    session.add(row)
    session.flush()
    return row


def runtime(session, ns, *, age=timedelta(days=60), metadata=None, account=None, status="started"):
    """A runtime (``ai_runtime``) operation: its reservation was committed with the claim."""
    row = AIOperation(id=str(uuid.uuid4()), user_id=ns.user, organization_id=ns.org, status=status,
                      operation_type="score_batch", router_version="test", policy_version="test",
                      billing_account_id=account, idempotency_key=f"idem-{uuid.uuid4().hex}",
                      metadata_json={"idempotency_protected": True} if metadata is None else metadata,
                      created_at=naive(now(session) - age), updated_at=naive(now(session) - age))
    session.add(row)
    session.flush()
    return row


def decide(session, operation, staff, disposition="no_compensation_owed", *, command=None, **kwargs):
    return record_operation_decision(
        session, decision_command_id=command or f"d-{uuid.uuid4().hex[:8]}", ai_operation_id=operation.id,
        disposition=disposition, evidence_reference="review:fixture-operation-evidence",
        reason="the operation's process is gone; the fixture's evidence decides it", reviewer_user_id=staff.id,
        **kwargs)


def classify(session, operation, max_turn_seconds=BOUND):
    return bm.classify_legacy_operation(operation, at=now(session), max_turn_seconds=max_turn_seconds)


def op_codes(result):
    return sorted(c for c in codes(result) if c.startswith("legacy_operation_"))


# ---------------------------------------------------------------------------
# D-3: the age limit is explicit configuration; without it everything blocks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    (None, None), (True, None), (0, None), (299, None), ("abc", None), ("", None), (1.5e3, None),
    (300, 300), ("1800", 1800), (BOUND, BOUND),
])
def test_the_age_limit_has_no_default_and_refuses_values_below_the_floor(value, expected):
    config = {} if value is None else {KEY: value}
    assert bm.migration_max_turn_seconds(config) == expected


def test_without_a_configured_age_limit_every_unclosed_operation_quarantines_as_before(db):
    session = db.session
    ns = personal(session)
    turn(session, ns, age=timedelta(days=30))
    runtime(session, ns)
    assert current_app.config.get(KEY) is None
    result = backfill(session, ns)
    assert result.outcome == "quarantined" and op_codes(result) == ["legacy_operation_in_flight"]
    assert {c["subject"] for c in result.quarantine_codes_json if c["code"] == "legacy_operation_in_flight"} \
        == {o.id for o in session.query(AIOperation)}
    assert entries(session, ns.account) == []


# ---------------------------------------------------------------------------
# The five classes (P4.1 X1, refined for Phase 14; reads only)
# ---------------------------------------------------------------------------

def test_a_turn_inside_the_age_limit_is_in_flight(db, bound):
    session = db.session
    ns = personal(session)
    row = turn(session, ns, age=timedelta(minutes=5))
    assert classify(session, row)["class"] == "in_flight"
    assert op_codes(backfill(session, ns)) == ["legacy_operation_in_flight"]


def test_a_killed_turn_past_the_limit_is_stale_turn_evidence_and_needs_a_decision(db, bound):
    session = db.session
    ns = personal(session)
    row = turn(session, ns)
    item = classify(session, row)
    assert (item["class"], item["reason"], item["x1_class"]) == (
        "stale_turn_evidence", "no_recorded_outcome", "stale_turn_evidence")
    result = backfill(session, ns)
    assert op_codes(result) == ["legacy_operation_decision_required"]


def test_a_settled_turn_whose_status_write_failed_is_already_charged_and_does_not_block(db, bound):
    session = db.session
    ns = personal(session)
    before = legacy_snapshot(session)
    row = turn(session, ns, lifecycle={"outcome": "settled", "settlement_ok": True, "balance_committed": True,
                                       "settled_credits": 4000})
    assert classify(session, row)["class"] == "already_charged"
    plan = plan_account_backfill(session, billing_account_id=ns.account)
    assert not [c for c in plan["quarantine"] if c["code"].startswith("legacy_operation_")]
    assert plan["evidence"]["unclosed_operations"] == [{
        "operation_id": row.id, "class": "already_charged", "reason": "settled_with_durable_charge",
        "evidence_fingerprint": bm.operation_fingerprint(row)}]
    # Phase 14 never writes a legacy row: the operation stays 'started', every legacy value is unchanged.
    assert session.get(AIOperation, row.id).status == "started" and legacy_snapshot(session) == before


@pytest.mark.parametrize("facts", [
    {"outcome": "settled", "settlement_ok": True},                       # durability not observed
    {"outcome": "settled", "settlement_ok": False, "balance_committed": True},
    {"outcome": "settled", "settlement_ok": "true", "balance_committed": "true"},  # not real booleans
    {"outcome": "generation_failed", "settlement_ok": True, "balance_committed": True},
])
def test_a_settled_claim_without_durable_charge_facts_is_not_already_charged(db, bound, facts):
    session = db.session
    ns = personal(session)
    item = classify(session, turn(session, ns, lifecycle=facts))
    assert (item["class"], item["reason"]) == ("stale_turn_evidence", "outcome_without_durable_charge")


def test_an_aged_unbound_runtime_operation_is_an_outstanding_reservation(db, bound):
    session = db.session
    ns = personal(session)
    row = runtime(session, ns)
    assert classify(session, row)["class"] == "outstanding_reservation"
    assert op_codes(backfill(session, ns)) == ["legacy_operation_decision_required"]
    young = runtime(session, ns, age=timedelta(minutes=5))
    assert classify(session, young)["class"] == "in_flight"


@pytest.mark.parametrize("make,reason", [
    (lambda s, ns: turn(s, ns, lifecycle={"version": "p9.9-unknown"}), "unrecognised_turn_claim"),
    (lambda s, ns: turn(s, ns, status="queued"), "unrecognized_status"),
    (lambda s, ns: runtime(s, ns, metadata={"turn_lifecycle": {"version": TURN_LIFECYCLE_VERSION}}),
     "unrecognized_runtime_metadata"),
    (lambda s, ns: runtime(s, ns, metadata=["not", "a", "dict"]), "unrecognized_runtime_metadata"),
])
def test_anything_the_classifier_does_not_recognise_blocks_and_cannot_be_decided(db, bound, make, reason):
    session = db.session
    ns = personal(session)
    row = make(session, ns)
    item = classify(session, row)
    assert (item["class"], item["reason"]) == ("unrecognized", reason)
    assert op_codes(backfill(session, ns)) == ["legacy_operation_unrecognized"]
    staff, _grant = reviewer(session)
    with pytest.raises(MigrationError, match="unrecognized operation cannot take a decision"):
        decide(session, row, staff)


def test_a_runtime_operation_bound_to_a_billing_account_stays_in_flight(db, bound):
    session = db.session
    ns = personal(session)
    row = runtime(session, ns, account=ns.account)
    assert classify(session, row)["class"] == "in_flight"
    staff, _grant = reviewer(session)
    with pytest.raises(MigrationError, match="in_flight operation cannot take a decision"):
        decide(session, row, staff)


def test_closed_operations_are_ignored_and_cannot_be_decided(db, bound):
    session = db.session
    ns = personal(session)
    row = runtime(session, ns, status="succeeded")
    assert classify(session, row) is None
    assert op_codes(backfill(session, ns)) == []
    staff, _grant = reviewer(session)
    with pytest.raises(MigrationError, match="closed operation cannot take a decision"):
        decide(session, row, staff)


# ---------------------------------------------------------------------------
# Decisions: what they unblock, what they never do
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("make", [turn, runtime])
def test_no_compensation_owed_lets_the_backfill_proceed_without_touching_the_operation(db, bound, make):
    session = db.session
    ns = personal(session)
    row = make(session, ns)
    staff, staff_grant = reviewer(session)
    before = legacy_snapshot(session)
    decision, state = decide(session, row, staff)
    assert state == "inserted" and decision.disposition == "no_compensation_owed"
    assert (decision.amount, decision.beneficiary_billing_account_id) == (None, None)
    assert decision.staff_permission_grant_id == staff_grant.id
    assert decision.evidence_fingerprint == bm.operation_fingerprint(row)
    assert decision.evidence_json["recommendation"]["disposition"] in ("no_compensation_owed", "individual_review")
    result = backfill(session, ns)
    assert op_codes(result) == [] and result.outcome == "opened"
    reported = result.evidence_json["unclosed_operations"] if "unclosed_operations" in result.evidence_json \
        else plan_account_backfill(session, billing_account_id=ns.account)["evidence"]["unclosed_operations"]
    assert [(r["operation_id"], r["decision_id"], r["disposition"]) for r in reported] == [
        (row.id, decision.id, "no_compensation_owed")]
    assert session.get(AIOperation, row.id).status == "started" and legacy_snapshot(session) == before


def test_compensation_owed_moves_no_money_and_keeps_the_account_quarantined(db, bound):
    session = db.session
    ns = personal(session)
    row = turn(session, ns)
    staff, _grant = reviewer(session)
    before = legacy_snapshot(session)
    decision, _state = decide(session, row, staff, "compensation_owed", amount=4000,
                              beneficiary_billing_account_id=ns.account)
    assert (decision.amount, decision.beneficiary_billing_account_id) == (4000, ns.account)
    result = backfill(session, ns)
    assert result.outcome == "quarantined" and op_codes(result) == ["legacy_operation_compensation_pending"]
    assert entries(session, ns.account) == [] and legacy_snapshot(session) == before


def test_a_decision_stops_applying_once_the_operation_changes(db, bound):
    session = db.session
    ns = personal(session)
    row = runtime(session, ns)
    staff, _grant = reviewer(session)
    decide(session, row, staff)
    old_write = row.updated_at
    row.charged_credits = 7  # an ORM write also stamps updated_at, so the row may be live again
    session.flush()
    assert op_codes(backfill(session, ns)) == ["legacy_operation_in_flight"]
    # A change that leaves the last-write time old (e.g. written outside the ORM) still ends the decision.
    session.execute(sa.update(AIOperation).where(AIOperation.id == row.id).values(updated_at=old_write))
    session.expire(row)
    assert op_codes(backfill(session, ns)) == ["legacy_operation_decision_evidence_changed"]
    # The changed evidence can take its own, new decision.
    decision, state = decide(session, row, staff)
    assert state == "inserted" and op_codes(backfill(session, ns)) == []


def test_a_decision_is_idempotent_and_a_second_one_for_the_same_evidence_is_refused(db, bound):
    session = db.session
    ns = personal(session)
    row = runtime(session, ns)
    staff, _grant = reviewer(session)
    first, state = decide(session, row, staff, command="same-command")
    again, replay = decide(session, row, staff, command="same-command")
    assert (state, replay, again.id) == ("inserted", "duplicate", first.id)
    with pytest.raises(MigrationConflictError, match="different facts"):
        decide(session, row, staff, "compensation_owed", command="same-command", amount=1,
               beneficiary_billing_account_id=ns.account)
    with pytest.raises(MigrationConflictError, match="already has a decision"):
        decide(session, row, staff, command="another-command")
    assert session.query(BillingMigrationOperationDecision).count() == 1


def test_no_decision_is_recorded_without_a_configured_age_limit(db):
    session = db.session
    ns = personal(session)
    row = runtime(session, ns)
    staff, _grant = reviewer(session)
    with pytest.raises(MigrationError, match=f"{KEY} is not configured"):
        decide(session, row, staff)


@pytest.mark.parametrize("disposition,kwargs,match", [
    ("refund_it", {}, "disposition must be one of"),
    ("no_compensation_owed", {"amount": 5}, "takes no amount or beneficiary"),
    ("compensation_owed", {}, "positive integer amount"),
    ("compensation_owed", {"amount": 0, "beneficiary_billing_account_id": "x"}, "positive integer amount"),
    ("compensation_owed", {"amount": True, "beneficiary_billing_account_id": "x"}, "positive integer amount"),
])
def test_a_decision_needs_a_known_disposition_and_a_consistent_amount(db, bound, disposition, kwargs, match):
    session = db.session
    ns = personal(session)
    row = turn(session, ns)
    staff, _grant = reviewer(session)
    with pytest.raises(MigrationError, match=match):
        decide(session, row, staff, disposition, **kwargs)


def test_compensation_is_owed_only_to_the_operations_own_organization_and_within_its_estimate(db, bound):
    session = db.session
    ns = personal(session)
    other = personal(session)
    row = turn(session, ns)  # estimated_reservation 4000
    staff, _grant = reviewer(session)
    with pytest.raises(MigrationError, match="own organization's billing account"):
        decide(session, row, staff, "compensation_owed", amount=10, beneficiary_billing_account_id=other.account)
    with pytest.raises(MigrationError, match="cannot exceed the reservation"):
        decide(session, row, staff, "compensation_owed", amount=4001, beneficiary_billing_account_id=ns.account)
    assert session.query(BillingMigrationOperationDecision).count() == 0


def test_decision_separation_of_duties(db, bound):
    session = db.session
    ns = personal(session)
    row = runtime(session, ns)
    holder = session.get(User, ns.user)
    with pytest.raises(MigrationPermissionError, match="does not hold"):
        decide(session, row, user(session, "nobody"))
    # The operation's own user, even with a review grant.
    with pytest.raises(MigrationPermissionError, match="their own operation"):
        decide(session, row, holder)
    staff, _grant = reviewer(session)
    session.add(OrganizationMember(organization_id=ns.org, user_id=staff.id, role="collaborator", status="removed"))
    session.flush()
    with pytest.raises(MigrationPermissionError, match="member or owner"):
        decide(session, row, staff)
    assert session.query(BillingMigrationOperationDecision).count() == 0


def test_one_tenants_decision_never_clears_another_tenants_operation(db, bound):
    session = db.session
    first, second = personal(session), personal(session)
    a, b = runtime(session, first), runtime(session, second)
    staff, _grant = reviewer(session)
    decide(session, a, staff)
    assert op_codes(backfill(session, first)) == []
    assert op_codes(backfill(session, second)) == ["legacy_operation_decision_required"]
    assert [c["subject"] for c in plan_account_backfill(session, billing_account_id=second.account)["quarantine"]
            if c["code"] == "legacy_operation_decision_required"] == [b.id]


def test_a_reviewer_tied_to_any_organization_the_operation_blocks_cannot_decide_it(db, bound):
    """The subject's operation blocks every organization the subject owns or belongs to, so a member of any of
    them (here only of the subject's second organization) has a conflict."""
    session = db.session
    ns = personal(session)
    holder = session.get(User, ns.user)
    staff, _grant = reviewer(session)
    second = organization(session, staff, members=(holder,))  # staff owns it; the subject is a member
    row = runtime(session, ns)
    assert bm.operation_affected_organization_ids(session, row) == {ns.org, second.org}
    with pytest.raises(MigrationPermissionError, match="organization the operation blocks"):
        decide(session, row, staff)
    other, _grant = reviewer(session)
    session.add(OrganizationMember(organization_id=second.org, user_id=other.id, role="collaborator",
                                   status="active"))
    session.flush()
    with pytest.raises(MigrationPermissionError, match="organization the operation blocks"):
        decide(session, row, other)
    assert session.query(BillingMigrationOperationDecision).count() == 0
    outsider, _grant = reviewer(session)
    _decision, state = decide(session, row, outsider)
    assert state == "inserted"


@pytest.mark.parametrize("tie", ["payment", "stripe_customer"])
def test_a_reviewer_in_an_organization_the_subject_pays_for_cannot_decide_it(db, bound, tie):
    """Phase 14 also counts an account's payers among its candidates, so the subject's operation blocks an
    organization they pay for without any membership; its members have a conflict."""
    session = db.session
    ns = personal(session)
    holder = session.get(User, ns.user)
    staff, _grant = reviewer(session)
    paid = organization(session, user(session, "paid-owner"), members=(staff,),
                        customer=f"cus_{uuid.uuid4().hex[:12]}" if tie == "stripe_customer" else None)
    if tie == "payment":
        payment(session, holder).billing_account_id = paid.account
    else:
        holder.stripe_customer_id = session.get(BillingAccount, paid.account).processor_customer_id
    session.flush()
    row = runtime(session, ns)
    assert paid.org in bm.operation_affected_organization_ids(session, row)
    with pytest.raises(MigrationPermissionError, match="organization the operation blocks"):
        decide(session, row, staff)


# ---------------------------------------------------------------------------
# Corrections: append-only superseding decisions
# ---------------------------------------------------------------------------

def test_a_correction_supersedes_the_current_decision_without_editing_it(db, bound):
    session = db.session
    ns = personal(session)
    row = turn(session, ns)
    staff, _grant = reviewer(session)
    first, _state = decide(session, row, staff, "compensation_owed", amount=4000,
                           beneficiary_billing_account_id=ns.account)
    assert op_codes(backfill(session, ns)) == ["legacy_operation_compensation_pending"]
    corrected, state = decide(session, row, staff, supersedes_decision_id=first.id)
    assert state == "inserted" and corrected.supersedes_decision_id == first.id
    assert session.get(BillingMigrationOperationDecision, first.id).disposition == "compensation_owed"  # unedited
    assert op_codes(backfill(session, ns)) == []
    status = bm.legacy_operation_status(row, at=now(session), max_turn_seconds=BOUND,
                                        decisions=[first, corrected])
    assert (status["decision_id"], status["supersedes_decision_id"]) == (corrected.id, first.id)
    # A chain never forks: the superseded decision cannot be superseded again, and only the current one can be.
    with pytest.raises(MigrationConflictError, match="supersede the current decision"):
        decide(session, row, staff, supersedes_decision_id=first.id)
    again, _state = decide(session, row, staff, "compensation_owed", amount=10,
                           beneficiary_billing_account_id=ns.account, supersedes_decision_id=corrected.id)
    assert op_codes(backfill(session, ns)) == ["legacy_operation_compensation_pending"]
    assert session.query(BillingMigrationOperationDecision).count() == 3 and again.supersedes_decision_id == corrected.id


def test_a_correction_cannot_supersede_a_decision_for_old_evidence_or_another_operation(db, bound):
    session = db.session
    ns = personal(session)
    row, other = runtime(session, ns), runtime(session, ns)
    staff, _grant = reviewer(session)
    first, _state = decide(session, row, staff)
    with pytest.raises(MigrationConflictError, match="supersede the current decision"):
        decide(session, other, staff, supersedes_decision_id=first.id)
    old_write = row.updated_at
    row.charged_credits = 3
    session.flush()
    session.execute(sa.update(AIOperation).where(AIOperation.id == row.id).values(updated_at=old_write))
    session.expire(row)
    with pytest.raises(MigrationConflictError, match="supersede the current decision"):
        decide(session, row, staff, supersedes_decision_id=first.id)
    fresh, state = decide(session, row, staff)  # changed evidence takes its own original decision
    assert state == "inserted" and fresh.supersedes_decision_id is None


def test_replaying_a_recorded_command_is_stable_after_the_operation_closes(db, bound):
    session = db.session
    ns = personal(session)
    row = runtime(session, ns)
    staff, _grant = reviewer(session)
    first, _state = decide(session, row, staff, command="stable")
    row.status = "failed"
    session.flush()
    again, state = decide(session, row, staff, command="stable")
    assert (state, again.id) == ("duplicate", first.id)
    with pytest.raises(MigrationConflictError, match="different facts"):
        decide(session, row, staff, command="stable", supersedes_decision_id=first.id)


# ---------------------------------------------------------------------------
# The review report: evidence and a recommendation per case, never applied
# ---------------------------------------------------------------------------

def test_the_review_recommends_no_compensation_only_when_the_monthly_cycle_reset_and_no_persistent_credit(db, bound):
    session = db.session
    ns = personal(session, days_ago=3)  # the holder's cycle reset 3 days ago
    lapsed = runtime(session, ns, age=timedelta(days=60))
    with_grant = personal(session, days_ago=3)
    grant(session, session.get(User, with_grant.user), 1000, 1000, granted_at=now(session) - timedelta(days=90))
    funded = runtime(session, with_grant, age=timedelta(days=60))
    no_reset = personal(session, days_ago=90)
    unreset = runtime(session, no_reset, age=timedelta(days=60))
    before = session.query(BillingMigrationOperationDecision).count()
    report = unclosed_operation_review(session)
    rows = {r["operation_id"]: r for r in report["operations"]}
    assert report["max_turn_seconds"] == BOUND and report["needs_decision"] == 3 == report["blocking"]
    assert rows[lapsed.id]["evidence"]["recommendation"]["disposition"] == "no_compensation_owed"
    assert rows[lapsed.id]["evidence"]["subject"]["persistent_grants_before_claim"] == 0
    assert rows[funded.id]["evidence"]["recommendation"]["disposition"] == "individual_review"
    assert rows[unreset.id]["evidence"]["recommendation"]["disposition"] == "individual_review"
    # Reads only: nothing is decided by the report.
    assert session.query(BillingMigrationOperationDecision).count() == before
    assert op_codes(backfill(session, ns)) == ["legacy_operation_decision_required"]


def test_a_runtime_retry_that_reclaimed_an_old_row_is_in_flight_not_outstanding(db, bound):
    """ai_runtime._claim_operation puts a failed row back to 'started' without changing created_at."""
    session = db.session
    ns = personal(session)
    row = runtime(session, ns, age=timedelta(hours=3))
    row.updated_at = naive(now(session) - timedelta(seconds=10))
    session.flush()
    item = classify(session, row)
    assert (item["class"], item["reason"]) == ("in_flight", "written_within_age_limit")
    assert op_codes(backfill(session, ns)) == ["legacy_operation_in_flight"]
    staff, _grant = reviewer(session)
    with pytest.raises(MigrationError, match="in_flight operation cannot take a decision"):
        decide(session, row, staff)


def test_a_shared_pool_recommendation_needs_the_organizations_cycle_to_have_reset(db, bound):
    """Shared-pool debits restamp the member's credits_reset_at, so it is no evidence of a cycle reset."""
    session = db.session
    holder = user(session, "pooled", plan="team", reset=now(session) - timedelta(days=1))
    for settings, expected in (
        (None, "individual_review"),  # no organization meter: unknown, never "reset"
        ({"thinking_power": {"cycle_reset_at": naive(now(session) - timedelta(days=90)).isoformat()}},
         "individual_review"),
        ({"thinking_power": {"cycle_reset_at": naive(now(session) - timedelta(days=1)).isoformat()}},
         "no_compensation_owed"),
    ):
        ns = organization(session, holder, settings=settings)
        row = runtime(session, type("Ns", (), {"user": holder.id, "org": ns.org})(), age=timedelta(days=60))
        evidence = bm.operation_review_evidence(session, row, at=now(session), max_turn_seconds=BOUND)
        assert evidence["monthly_cycle_reset_since_claim"]["meter_used"] == "organization"
        assert evidence["recommendation"]["disposition"] == expected, settings


@pytest.mark.parametrize("field,value", [
    ("result_json", {"changed": True}), ("total_provider_cost_usd", 1), ("policy_version", "other"),
    ("final_model", "other-model"), ("metadata_json", {"idempotency_protected": True, "x": 1}),
])
def test_every_column_of_the_operation_is_in_its_fingerprint(db, bound, field, value):
    session = db.session
    ns = personal(session)
    row = runtime(session, ns)
    before = bm.operation_fingerprint(row)
    setattr(row, field, value)
    assert bm.operation_fingerprint(row) != before


def test_decided_operations_no_longer_block_the_rehearsal_drain_gate(db, bound):
    session = db.session
    ns = personal(session)
    row = runtime(session, ns)

    def drained():
        found = next(f for f in br.rehearsal_preconditions(session, environment="fixtures")["findings"]
                     if f["check"] == "no_in_flight_ai_operations")
        return found["detail"]

    assert drained() == {"started_operations": [row.id],
                         "blocking_by_code": {"legacy_operation_decision_required": 1}}
    staff, _grant = reviewer(session)
    decide(session, row, staff)
    assert drained() == {"started_operations": [], "blocking_by_code": {}}


# ---------------------------------------------------------------------------
# Schema: the revision, its literal checks, SQLite guards and round trip
# ---------------------------------------------------------------------------

def _revision():
    from alembic.script import ScriptDirectory
    from tests.test_billing_migration import MIGRATIONS_DIR
    return ScriptDirectory(str(MIGRATIONS_DIR)).get_revision(REVISION).module


def test_revision_extends_phase17_and_is_the_single_head():
    from alembic.script import ScriptDirectory
    from tests.test_billing_migration import MIGRATIONS_DIR
    script = ScriptDirectory(str(MIGRATIONS_DIR))
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == "f3a5c7e9b1d2"


def test_revision_check_constraints_are_literal_copies_of_the_model():
    module = _revision()
    model = {c.name: str(c.sqltext) for c in BillingMigrationOperationDecision.__table__.constraints
             if isinstance(c, sa.CheckConstraint)}
    assert {name: sql for sql, name in module.CHECKS} == model


def _sqlite_engine(tmp_path):
    from app import db as flask_db
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'bi1.sqlite'}")
    flask_db.metadata.create_all(engine, tables=[t for t in flask_db.metadata.sorted_tables if t.name != TABLE])
    return engine


def _schema(engine):
    with engine.connect() as connection:
        return sorted(tuple(r) for r in connection.execute(sa.text(
            "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")))


def test_sqlite_round_trip_is_exact_and_the_guard_refuses_a_forged_decision(tmp_path):
    module = _revision()
    engine = _sqlite_engine(tmp_path)
    try:
        parent = _schema(engine)
        with _ops(engine):
            module.upgrade()
        names = {row[1] for row in _schema(engine)}
        assert TABLE in names and set(module.SQLITE_TRIGGERS) <= names
        with _ops(engine):
            module.downgrade()
        assert _schema(engine) == parent
        with _ops(engine):
            module.upgrade()
        with engine.begin() as connection:
            # Every guard is checked before any row exists: a forged decision is refused.
            with pytest.raises(sa.exc.DatabaseError, match="review grant"):
                connection.execute(sa.text(
                    f"INSERT INTO {TABLE} (id, decision_key, ai_operation_id, operation_class, disposition, "
                    "evidence_json, evidence_fingerprint, evidence_reference, reason, rule_version, "
                    "reviewer_user_id, staff_permission_grant_id, decided_at, request_fingerprint, "
                    "idempotency_registry_id) VALUES ('d', 'k', 'op', 'outstanding_reservation', "
                    "'no_compensation_owed', '{}', :fp, 'ref', 'why', "
                    "'jaspen.billing.migration.operation_decision.v1', 'rev', 'grant', CURRENT_TIMESTAMP, :fp, 'reg')"
                ), {"fp": "a" * 64})
        # With a decision present (inserted around the dropped guard, for this check only), downgrade refuses
        # and leaves the table and the row in place.
        with engine.begin() as connection:
            connection.execute(sa.text("DROP TRIGGER trg_bi1_operation_decision_insert"))
            connection.execute(sa.text(
                f"INSERT INTO {TABLE} (id, decision_key, ai_operation_id, operation_class, disposition, "
                "evidence_json, evidence_fingerprint, evidence_reference, reason, rule_version, reviewer_user_id, "
                "staff_permission_grant_id, decided_at, request_fingerprint, idempotency_registry_id) VALUES "
                "('d', 'k', 'op', 'outstanding_reservation', 'no_compensation_owed', '{}', :fp, 'ref', 'why', "
                "'jaspen.billing.migration.operation_decision.v1', 'rev', 'grant', CURRENT_TIMESTAMP, :fp, 'reg')"
            ), {"fp": "a" * 64})
        with pytest.raises(module.OperationDecisionsNotEmptyError), _ops(engine):
            module.downgrade()
        with engine.connect() as connection:
            assert connection.execute(sa.text(f"SELECT count(*) FROM {TABLE}")).scalar_one() == 1
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# PostgreSQL 18.6: the fully migrated database, guards live
# ---------------------------------------------------------------------------

def _pg_world(engine, monkeypatch):
    monkeypatch.setattr(bm, "migration_max_turn_seconds", lambda config=None: BOUND)
    with migrated(engine) as session:
        ns = personal(session)
        row = runtime(session, ns)
        staff, staff_grant = reviewer(session)
        session.commit()
        return ns, row.id, staff.id, staff_grant.id


@PG
def test_postgres_a_recorded_decision_is_immutable_and_unblocks_the_migrated_backfill(monkeypatch):
    engine = _migrated_engine()
    try:
        ns, operation_id, staff_id, _grant_id = _pg_world(engine, monkeypatch)
        with migrated(engine) as session:
            decision, _state = record_operation_decision(
                session, decision_command_id=f"pg-{uuid.uuid4().hex[:8]}", ai_operation_id=operation_id,
                disposition="no_compensation_owed", evidence_reference="review:pg", reason="pg fixture",
                reviewer_user_id=staff_id)
            session.commit()
        with migrated(engine) as session:
            assert op_codes(backfill(session, ns)) == []
            session.commit()
        for statement in (f"UPDATE {TABLE} SET reason='changed' WHERE id=:id", f"DELETE FROM {TABLE} WHERE id=:id"):
            with engine.begin() as connection, pytest.raises(sa.exc.DBAPIError, match="immutable"):
                connection.execute(sa.text(statement), {"id": decision.id})
        with engine.begin() as connection, pytest.raises(sa.exc.DBAPIError, match="cannot be truncated"):
            connection.execute(sa.text(f"TRUNCATE {TABLE}"))
    finally:
        engine.dispose()


@PG
@pytest.mark.parametrize("change,match", [
    ("grant", "review grant"),
    ("subject", "unclosed, unbound operation"),
    ("closed", "unclosed, unbound operation"),
    ("registry", "own idempotency claim"),
    ("decided_at", "review grant"),
    ("supersede_other_evidence", "same operation and evidence"),
    ("reviewer_in_subjects_other_organization", "organization the operation blocks"),
    ("reviewer_in_organization_the_subject_pays", "organization the operation blocks"),
])
def test_postgres_the_guard_refuses_a_decision_written_around_the_command(monkeypatch, change, match):
    """Copy a real, valid decision's values into a forged insert and break exactly one fact."""
    engine = _migrated_engine()
    try:
        _ns, operation_id, staff_id, _grant_id = _pg_world(engine, monkeypatch)
        with migrated(engine) as session:
            # The real decision stays in this transaction (never committed), so its claim exists and
            # every fact but the one changed below is genuine.
            decision, _state = record_operation_decision(
                session, decision_command_id=f"pg-{uuid.uuid4().hex[:8]}", ai_operation_id=operation_id,
                disposition="no_compensation_owed", evidence_reference="review:pg", reason="pg fixture",
                reviewer_user_id=staff_id)
            values = {c.name: getattr(decision, c.name) for c in BillingMigrationOperationDecision.__table__.columns
                      if c.name != "created_at"}
            values.update(id=str(uuid.uuid4()), evidence_fingerprint="b" * 64)
            if change == "grant":
                values["staff_permission_grant_id"] = "no-such-grant"
            elif change == "subject":
                values["subject_user_id"] = None
            elif change == "closed":
                session.execute(sa.text("UPDATE ai_operations SET status='failed' WHERE id=:id"), {"id": operation_id})
            elif change == "registry":
                values["decision_key"] = "migration-operation-decision:not-claimed"
            elif change == "decided_at":
                values["decided_at"] = values["decided_at"] - timedelta(seconds=5)
            elif change == "supersede_other_evidence":
                values["supersedes_decision_id"] = decision.id  # the forged row's evidence differs
            elif change == "reviewer_in_subjects_other_organization":
                subject = session.get(User, values["subject_user_id"])
                other = organization(session, user(session, "other-owner"), members=(subject,))
                session.add(OrganizationMember(organization_id=other.org, user_id=staff_id, role="collaborator",
                                               status="active"))
                session.flush()
                values["evidence_fingerprint"] = decision.evidence_fingerprint
                values["supersedes_decision_id"] = decision.id
            elif change == "reviewer_in_organization_the_subject_pays":
                subject = session.get(User, values["subject_user_id"])
                paid = organization(session, user(session, "paid-owner"))
                session.add(OrganizationMember(organization_id=paid.org, user_id=staff_id, role="collaborator",
                                               status="active"))
                payment(session, subject).billing_account_id = paid.account
                session.flush()
                values["evidence_fingerprint"] = decision.evidence_fingerprint
                values["supersedes_decision_id"] = decision.id
            with pytest.raises(sa.exc.DBAPIError, match=match):
                session.execute(BillingMigrationOperationDecision.__table__.insert().values(**values))
            session.rollback()
    finally:
        engine.dispose()


@PG
def test_postgres_two_reviewers_racing_on_the_same_evidence_record_one_decision(monkeypatch):
    engine = _migrated_engine()
    try:
        _ns, operation_id, staff_id, _grant_id = _pg_world(engine, monkeypatch)
        with migrated(engine) as session:
            second, _grant = reviewer(session)
            session.commit()
            second_id = second.id
        barrier = threading.Barrier(2)

        def attempt(reviewer_id):
            with migrated(engine) as session:
                barrier.wait()
                try:
                    record_operation_decision(
                        session, decision_command_id=f"race-{uuid.uuid4().hex[:8]}", ai_operation_id=operation_id,
                        disposition="no_compensation_owed", evidence_reference="review:race", reason="race",
                        reviewer_user_id=reviewer_id)
                    session.commit()
                    return "inserted"
                except (MigrationConflictError, sa.exc.IntegrityError):
                    session.rollback()
                    return "refused"

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = sorted(pool.map(attempt, [staff_id, second_id]))
        assert outcomes == ["inserted", "refused"]
        with migrated(engine) as session:
            assert session.execute(sa.select(sa.func.count()).select_from(BillingMigrationOperationDecision)
                                   .where(BillingMigrationOperationDecision.ai_operation_id == operation_id)
                                   ).scalar_one() == 1
    finally:
        engine.dispose()


@PG
def test_postgres_two_racing_corrections_of_one_decision_record_one(monkeypatch):
    engine = _migrated_engine()
    try:
        _ns, operation_id, staff_id, _grant_id = _pg_world(engine, monkeypatch)
        with migrated(engine) as session:
            first, _state = record_operation_decision(
                session, decision_command_id=f"root-{uuid.uuid4().hex[:8]}", ai_operation_id=operation_id,
                disposition="no_compensation_owed", evidence_reference="review:race", reason="root",
                reviewer_user_id=staff_id)
            session.commit()
            first_id = first.id
        barrier = threading.Barrier(2)

        def correct(_):
            with migrated(engine) as session:
                barrier.wait()
                try:
                    record_operation_decision(
                        session, decision_command_id=f"fix-{uuid.uuid4().hex[:8]}", ai_operation_id=operation_id,
                        disposition="no_compensation_owed", evidence_reference="review:race", reason="correction",
                        reviewer_user_id=staff_id, supersedes_decision_id=first_id)
                    session.commit()
                    return "inserted"
                except (MigrationConflictError, sa.exc.IntegrityError):
                    session.rollback()
                    return "refused"

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert sorted(pool.map(correct, range(2))) == ["inserted", "refused"]
        with migrated(engine) as session:
            assert session.execute(sa.select(sa.func.count()).select_from(BillingMigrationOperationDecision).where(
                BillingMigrationOperationDecision.supersedes_decision_id == first_id)).scalar_one() == 1
    finally:
        engine.dispose()


@PG
def test_postgres_round_trip_is_exact():
    """On a separate fresh database at the BI-1 head (TEST_BI1_ROUNDTRIP_DATABASE_URL)."""
    url = os.environ.get("TEST_BI1_ROUNDTRIP_DATABASE_URL")
    if not url:
        pytest.skip("TEST_BI1_ROUNDTRIP_DATABASE_URL is not configured")
    from tests.test_billing_rehearsal import _pg_signature
    module = _revision()
    engine = sa.create_engine(url)
    try:
        with engine.connect() as connection:
            if connection.execute(sa.text(f"SELECT 1 FROM {TABLE} LIMIT 1")).first():
                pytest.skip("the round-trip database must be freshly migrated and empty")
        head = _pg_signature(engine)
        with _ops(engine):
            module.downgrade()
        parent = _pg_signature(engine)
        assert parent != head and TABLE not in {row[0] for row in parent["columns"]}
        with _ops(engine):
            module.upgrade()
        assert _pg_signature(engine) == head
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Phase 16 per-account rows use the same Phase 14 status
# ---------------------------------------------------------------------------

def _shadow_operation_rows(session, ns):
    import app.billing_shadow as bs
    report = bs.shadow_compare_account(session, billing_account_id=ns.account, at=now(session))
    return [r for r in report["comparisons"] if r["comparison"] == "legacy_in_flight_operation"]


def test_shadow_per_account_rows_follow_the_phase14_status(db, bound):
    session = db.session
    ns = personal(session)
    row = runtime(session, ns)
    [found] = _shadow_operation_rows(session, ns)
    assert (found["subject"], found["special_case"]) == (row.id, "stale_operation_not_released")
    assert found["legacy"]["evidence"]["classification"] == "outstanding_reservation"
    young = runtime(session, ns, age=timedelta(minutes=1))
    labels = {r["subject"]: r["legacy"]["evidence"]["classification"] for r in _shadow_operation_rows(session, ns)}
    assert labels == {row.id: "outstanding_reservation", young.id: "in_flight"}
    staff, _grant = reviewer(session)
    decide(session, row, staff)
    # Cleared by a recorded decision: no longer in flight, exactly as in Phase 14 and the drain gate.
    assert [r["subject"] for r in _shadow_operation_rows(session, ns)] == [young.id]


def test_shadow_without_an_age_limit_still_reports_every_unclosed_operation(db):
    session = db.session
    ns = personal(session)
    row = runtime(session, ns)
    [found] = _shadow_operation_rows(session, ns)
    assert (found["subject"], found["special_case"], found["legacy"]["evidence"]["classification"]) == (
        row.id, "in_flight_operation", "in_flight")


# ---------------------------------------------------------------------------
# Configuration and the operator command line
# ---------------------------------------------------------------------------

def _cli(app, argv, capsys):
    import importlib.util
    from tests.test_billing_migration import BACKEND
    spec = importlib.util.spec_from_file_location("billing_migration_evidence",
                                                  BACKEND / "scripts" / "billing_migration_evidence.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    code = module.run(argv, app=app)
    import json
    return code, json.loads(capsys.readouterr().out or "null")


def test_the_age_limit_is_read_from_the_environment_with_no_default():
    """create_app copies the variable as given (no default); building another app here would rebind the shared
    extensions for every later test, so the copy is checked in the factory and the parsing on its values."""
    from tests.test_billing_migration import BACKEND
    factory = (BACKEND / "app" / "__init__.py").read_text()
    assert ("app.config['BILLING_MIGRATION_MAX_TURN_SECONDS'] = os.getenv('BILLING_MIGRATION_MAX_TURN_SECONDS')"
            in factory)
    for raw, expected in ((None, None), ("1800", 1800), ("60", None), (" 900 ", 900), ("30m", None)):
        assert bm.migration_max_turn_seconds({KEY: raw}) == expected


@pytest.mark.parametrize("variable,value", [("APP_ENV", "production"), ("STRIPE_SECRET_KEY", "sk_live_example")])
def test_the_command_line_refuses_a_production_runtime(app, capsys, monkeypatch, variable, value):
    monkeypatch.setenv(variable, value)
    code, out = _cli(app, ["operation-review"], capsys)
    assert code == 2 and "production runtime" in out["error"]


def test_the_command_line_writes_nothing_without_confirmation(db, app, bound, capsys):
    session = db.session
    ns = personal(session)
    row = runtime(session, ns)
    staff, _grant = reviewer(session)
    session.commit()
    argv = ["record-operation-decision", "--decision-command-id", "cli-1", "--operation-id", row.id,
            "--disposition", "no_compensation_owed", "--evidence-reference", "review:cli", "--reason", "cli test",
            "--reviewer-user-id", staff.id]
    code, out = _cli(app, argv, capsys)
    assert code == 2 and "--confirm-write" in out["error"]
    assert session.query(BillingMigrationOperationDecision).count() == 0
    code, out = _cli(app, argv + ["--confirm-write"], capsys)
    assert code == 0 and (out["state"], out["operation_id"]) == ("inserted", row.id)
    code, review = _cli(app, ["operation-review"], capsys)
    assert code == 0 and review["max_turn_seconds"] == BOUND
    assert [(r["operation_id"], r["code"], r["disposition"]) for r in review["operations"]] == [
        (row.id, None, "no_compensation_owed")]
    code, out = _cli(app, argv[:-2] + ["--reviewer-user-id", ns.user, "--confirm-write"], capsys)
    assert code == 1 and out["type"] == "MigrationConflictError"
