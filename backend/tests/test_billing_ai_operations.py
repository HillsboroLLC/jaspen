"""Phase 12: AI reservations, capacity authorization, and delivery-based settlement.

Lifecycle specification D06, D21, D22, D23 and the founder-approved
delivery-based billability policy (2026-11-11, amended 2026-11-16: delivered
usage stays billable after the original deadline while the reservation lease
is live; every member has an individual fair-use allowance). Test IDs follow
the traceability matrix (T-AI, T-PRICE, T-CAPACITY); ``F1``..``F8`` mark the
Phase 12 audit regressions.

Service tests run on the ORM schema (SQLite, or an isolated PostgreSQL schema
when TEST_DATABASE_URL is set). ``test_sqlite_migration_*`` applies the Phase
12 revision on SQLite. ``test_postgres_migrated_*`` runs on the fully migrated
disposable PostgreSQL database where every Phase 3-12 guard is live.

Every rate, conversion, capacity number, and credit amount below is a test
fixture, not an approved commercial or capacity policy.
"""

from concurrent.futures import ThreadPoolExecutor
import contextlib
from datetime import timedelta
from decimal import Decimal
import os
from pathlib import Path
import threading
import uuid

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

import app.billing_ai_operations as ai
from app import db as flask_db
from app.billing_ai_operations import (
    AIBillingConflictError,
    AIBillingIsolationError,
    AIBillingStateError,
    CapacityPolicyRequiredError,
    PricingPolicyRequiredError,
    RunawayLimitError,
    StepAlreadySettledError,
    ReservationLapsedError,
    UnpricedModelError,
    authorize_ai_operation,
    check_provider_call,
    expire_ai_operation,
    preflight_ai_operation,
    record_provider_call,
    record_undelivered_operation,
    release_without_billable_usage,
    renew_ai_operation_reservation,
    settle_delivered_operation,
)
from app.billing_allocations import allocate_recurring_credits, expire_recurring_credits
from app.models import (
    AIOperation,
    BillingAccount,
    CapacityPolicyVersion,
    CreditLedgerEntry,
    CreditLot,
    CreditReservation,
    EntitlementDefinition,
    IdempotencyRegistry,
    PricingPolicyVersion,
    ProviderRateEntry,
)
from app.models_billing_phase12 import (
    AIAbsorbedUsage,
    AIBillingOperation,
    AICapacityDecision,
    AIOperationCheckpoint,
    AIProviderCallUsage,
)
from tests.test_billing_enterprise_contracts import DELIVERIES, SERVICE, Ns, seed_org, self_serve


BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = str(BACKEND_DIR / "migrations")
REVISION = "c8e0a2b4d6f1"
PARENT = "b4d6f8a0c2e5"
PHASE12_TABLES = (
    "ai_operation_checkpoints", "ai_absorbed_usage", "ai_provider_call_usage",
    "ai_capacity_decisions", "ai_billing_operations",
)
PG = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="local disposable PostgreSQL is not configured")

# Test fixtures only (per 1M tokens, USD) and a fixture conversion.
CLAUDE, GEMINI = ("anthropic", "claude-test"), ("google", "gemini-test")
RATES = {CLAUDE: ("3", "15"), GEMINI: ("1", "5")}
CREDITS_PER_USD = "1000"
WINDOW = {"key": "five_hour", "window_seconds": 5 * 3600, "max_operations": 50}
RUNAWAY = {"max_provider_attempts": 3, "max_tool_iterations": 4, "max_operation_seconds": 600,
           "reservation_lease_seconds": 120, "max_reserved_credits": 200, "max_call_input_tokens": 8000,
           "max_call_output_tokens": 8000, "max_operation_tokens": 40000}
# 2000/2000 tokens: Claude 36 credits, Gemini 12; the worst case is held.
MAX_IN = MAX_OUT = 2000


def db_now(session):
    return ai._clock(session)


def refused(session, error, match, fn, *args, **kwargs):
    savepoint = session.begin_nested()
    try:
        with pytest.raises(error, match=match):
            fn(*args, **kwargs)
    finally:
        savepoint.rollback()


def _utc(value):
    return ai._utc(value)


# ---------------------------------------------------------------------------
# Seeding: policies, entitlement, funded credits, operations
# ---------------------------------------------------------------------------

def pricing(session, *, rates=RATES, conversion=CREDITS_PER_USD, effective_at=None, supersede=True):
    """A draft -> approved -> effective pricing version (the PostgreSQL lifecycle path)."""
    now = db_now(session)
    effective_at = effective_at or now - timedelta(minutes=5)
    if supersede:
        for old in session.execute(sa.select(PricingPolicyVersion).where(
                PricingPolicyVersion.state == "effective")).scalars():
            old.state, old.superseded_at = "superseded", now
        session.flush()
    version = PricingPolicyVersion(
        version=f"phase12-test-{uuid.uuid4().hex[:10]}", state="draft", effective_at=effective_at,
        credit_conversion_version="phase12-test", rounding_rule="ceil_whole_credit",
        conversion_json={"credits_per_provider_usd": conversion} if conversion else {},
        customer_credit_impact=False, notice_required=False,
    )
    session.add(version)
    session.flush()
    for (provider, model), (input_rate, output_rate) in rates.items():
        session.add(ProviderRateEntry(
            pricing_policy_version_id=version.id, provider=provider, model=model, currency="usd",
            unit_basis="per_1m_tokens", input_rate=input_rate, output_rate=output_rate,
            source_reference="fixture:phase12", source_observed_at=now,
        ))
    session.flush()
    version.state, version.approved_at = "approved", now - timedelta(minutes=10)
    session.flush()
    version.state = "effective"
    session.flush()
    return version


def _scope_rules(overrides, windows):
    """{"max_concurrent", "windows"}; window_seconds/max_operations overrides apply to the first window."""
    overrides = dict(overrides or {})
    first = {**WINDOW, **{k: overrides.pop(k) for k in ("window_seconds", "max_operations") if k in overrides}}
    return {"max_concurrent": overrides.pop("max_concurrent", 10),
            "windows": windows if windows is not None else [first], **overrides}


def capacity(session, tier_keys, *, organization=None, member=None, member_windows=None,
             organization_windows=None, without_organization=False, runaway=None, priorities=None):
    now = db_now(session)
    for old in session.execute(sa.select(CapacityPolicyVersion).where(
            CapacityPolicyVersion.state == "effective")).scalars():
        old.state, old.superseded_at = "superseded", now
    session.flush()
    tiers = {}
    for key in tier_keys:
        tiers[key] = {"priority": (priorities or {}).get(key, 1),
                      "member": _scope_rules(member, member_windows)}
        if not without_organization:
            tiers[key]["organization"] = _scope_rules(organization, organization_windows)
    version = CapacityPolicyVersion(
        version=f"phase12-cap-{uuid.uuid4().hex[:10]}", state="draft", effective_at=now - timedelta(minutes=5),
        rules_json={"schema": "jaspen.capacity.v1", "tiers": tiers, "runaway": {**RUNAWAY, **(runaway or {})}},
    )
    session.add(version)
    session.flush()
    version.state, version.approved_at = "approved", now - timedelta(minutes=10)
    version.approval_evidence_reference = "approval:phase12-fixture"
    session.flush()
    version.state = "effective"
    session.flush()
    return version


def tier_key(session, sub):
    return session.get(EntitlementDefinition, sub.instance.entitlement_definition_id).key


def account(session, *, members=1, credits=500):
    """An organization with an active paid entitlement and one funded recurring lot valid now."""
    ns = seed_org(session, members=members)
    anchor = db_now(session) - timedelta(hours=3)
    sub = self_serve(session, ns, "month", credits=credits, anchor=anchor)
    _allocation, period, lot, _state = allocate_recurring_credits(
        session, billing_account_id=ns.account, entitlement_instance_id=sub.instance.id, period_index=0,
        opened_at=anchor + timedelta(hours=2), delivery_obligations=DELIVERIES,
        financial_line_id=sub.line, **SERVICE,
    )
    ns.sub, ns.lot, ns.period, ns.tier = sub, lot, period, tier_key(session, sub)
    return ns


def world(session, *, members=1, credits=500, **capacity_overrides):
    ns = account(session, members=members, credits=credits)
    ns.pricing = pricing(session)
    ns.capacity = capacity(session, [ns.tier], **capacity_overrides)
    return ns


def operation(session, ns, user=None, *, org=None):
    op = AIOperation(
        id=str(uuid.uuid4()), user_id=user or ns.owner, organization_id=org or ns.org,
        operation_type="conversation", router_version="test", policy_version="test",
    )
    session.add(op)
    session.flush()
    return op.id


def authorize(session, ns, op_id=None, user=None, *, step="step-1", candidates=(CLAUDE, GEMINI), org_id=None,
              max_in=MAX_IN, max_out=MAX_OUT, **kwargs):
    op_id = op_id or operation(session, ns, user, org=org_id)
    return authorize_ai_operation(
        session, operation_id=op_id, actor_user_id=user or ns.owner, step_key=step,
        candidates=list(candidates), max_input_tokens=max_in, max_output_tokens=max_out, **kwargs,
    )


def call(session, op_id, attempt=1, index=0, *, model=CLAUDE, outcome="succeeded", label="reported",
         tokens=(1000, 1000), component="primary", error=None):
    now = db_now(session)
    return record_provider_call(
        session, operation_id=op_id, attempt_number=attempt, call_index=index, component=component,
        provider=model[0], model=model[1], outcome=outcome, usage_label=label,
        input_tokens=None if label == "unknown" else tokens[0],
        output_tokens=None if label == "unknown" else tokens[1],
        requested_at=now - timedelta(seconds=2), finished_at=now,
        error_category=error or (None if outcome == "succeeded" else "provider_error"),
        provider_request_id=f"req-{attempt}-{index}",
    )


def sums(session, account_id):
    available, held = session.execute(sa.select(
        sa.func.coalesce(sa.func.sum(CreditLedgerEntry.available_delta), 0),
        sa.func.coalesce(sa.func.sum(CreditLedgerEntry.held_delta), 0),
    ).where(CreditLedgerEntry.billing_account_id == account_id)).one()
    return int(available), int(held)


def charged(session, op_id):
    return -int(session.execute(sa.select(sa.func.coalesce(sa.func.sum(CreditLedgerEntry.held_delta), 0)).where(
        CreditLedgerEntry.operation_id == op_id, CreditLedgerEntry.entry_type == "settlement")).scalar_one())


def entries(session, op_id, kind=None):
    query = sa.select(CreditLedgerEntry).where(CreditLedgerEntry.operation_id == op_id)
    if kind:
        query = query.where(CreditLedgerEntry.entry_type == kind)
    return session.execute(query).scalars().all()


def absorbed(session, op_id):
    return session.execute(sa.select(AIAbsorbedUsage).where(AIAbsorbedUsage.operation_id == op_id)
                           .order_by(AIAbsorbedUsage.recorded_at, AIAbsorbedUsage.attempt_number)).scalars().all()


def row_counts(session):
    tables = (AIBillingOperation, AICapacityDecision, AIProviderCallUsage, AIAbsorbedUsage,
              AIOperationCheckpoint, CreditReservation, CreditLedgerEntry, IdempotencyRegistry)
    return {t.__tablename__: session.execute(sa.select(sa.func.count()).select_from(t)).scalar_one()
            for t in tables}


# ---------------------------------------------------------------------------
# Binding and fail-closed pricing/capacity (T-PRICE, D21)
# ---------------------------------------------------------------------------

def test_authorization_binds_effective_versions_and_reserves_the_worst_case_candidate(db):
    session = db.session
    ns = world(session)
    result = authorize(session, ns)
    assert result.outcome == "authorized" and not result.replay
    assert result.required_credits == result.held_credits == 36  # Claude worst case, not Gemini's 12
    assert result.pricing_policy_version_id == ns.pricing.id
    assert result.capacity_policy_version_id == ns.capacity.id
    op = session.get(AIOperation, result.operation_id)
    assert (op.billing_account_id, op.pricing_policy_version_id, op.capacity_policy_version_id) == (
        ns.account, ns.pricing.id, ns.capacity.id)
    reservation = session.get(CreditReservation, result.reservation_id)
    assert reservation.capacity_policy_version_id == ns.capacity.id
    assert reservation.authorized_amount == RUNAWAY["max_reserved_credits"]
    assert sums(session, ns.account) == (500 - 36, 36)
    decision = session.execute(sa.select(AICapacityDecision)).scalar_one()
    assert decision.outcome == "authorized" and decision.tier_key == ns.tier


@pytest.mark.parametrize("candidates", [[CLAUDE, ("anthropic", "unpriced")], [("openai", "gpt-test")]])
def test_unknown_provider_or_model_fails_closed_before_any_write(db, candidates):
    session = db.session
    ns = world(session)
    op_id = operation(session, ns)
    before = row_counts(session)
    refused(session, UnpricedModelError, "no exact rate", authorize, session, ns, op_id, candidates=candidates)
    assert row_counts(session) == before


def test_missing_future_or_incomplete_pricing_policy_fails_closed(db):
    session = db.session
    ns = account(session)
    capacity(session, [ns.tier])
    refused(session, PricingPolicyRequiredError, "exactly one effective", authorize, session, ns)
    pricing(session, effective_at=db_now(session) + timedelta(hours=1))
    refused(session, PricingPolicyRequiredError, "exactly one effective", authorize, session, ns)
    pricing(session, conversion=None)
    refused(session, PricingPolicyRequiredError, "credits_per_provider_usd", authorize, session, ns)


def test_missing_invalid_or_uncovering_capacity_policy_fails_closed(db):
    session = db.session
    ns = account(session)
    pricing(session)
    refused(session, CapacityPolicyRequiredError, "exactly one effective", authorize, session, ns)
    capacity(session, ["some-other-plan"])
    refused(session, CapacityPolicyRequiredError, "no active entitlement", authorize, session, ns)
    capacity(session, [ns.tier], runaway={"max_provider_attempts": 0})
    refused(session, CapacityPolicyRequiredError, "max_provider_attempts", authorize, session, ns)


def test_a_later_pricing_version_never_reprices_an_operation_in_progress(db):
    session = db.session
    ns = world(session)
    result = authorize(session, ns)
    pricing(session, rates={CLAUDE: ("30", "150"), GEMINI: ("10", "50")})  # supersedes the bound version
    call(session, result.operation_id)
    settled = settle_delivered_operation(session, operation_id=result.operation_id, delivered_attempt_number=1)
    assert settled.charged_credits == 18  # (1000*3 + 1000*15) / 1M USD * 1000, under the bound version
    usage = session.execute(sa.select(AIProviderCallUsage)).scalar_one()
    assert session.get(ProviderRateEntry, usage.provider_rate_entry_id).pricing_policy_version_id == ns.pricing.id


def test_preflight_is_a_pure_read(db):
    session = db.session
    ns = world(session)
    op_id = operation(session, ns)
    before = row_counts(session)
    result = preflight_ai_operation(session, operation_id=op_id, actor_user_id=ns.owner,
                                    candidates=[CLAUDE, GEMINI], max_input_tokens=MAX_IN, max_output_tokens=MAX_OUT)
    assert result["required_credits"] == 36 and result["available_credits"] == 500 and result["sufficient"]
    assert row_counts(session) == before and session.get(AIOperation, op_id).pricing_policy_version_id is None


# ---------------------------------------------------------------------------
# Reservation, replay, and exhaustion (T-AI-01..03, D23)
# ---------------------------------------------------------------------------

def test_credit_exhaustion_writes_nothing_and_leaves_the_operation_resumable(db):
    session = db.session
    ns = world(session, credits=20)
    op_id = operation(session, ns)
    before = row_counts(session)
    result = authorize(session, ns, op_id)
    assert (result.outcome, result.required_credits, result.available_credits) == ("credit_exhausted", 36, 20)
    assert row_counts(session) == before
    assert session.get(AIBillingOperation, op_id) is None


def test_replay_returns_the_recorded_result_and_conflicting_reuse_is_refused(db):
    session = db.session
    ns = world(session)
    op_id = operation(session, ns)
    first = authorize(session, ns, op_id)
    before = row_counts(session)
    again = authorize(session, ns, op_id)
    assert again.replay and again.reservation_id == first.reservation_id and row_counts(session) == before
    refused(session, AIBillingConflictError, "different facts", authorize, session, ns, op_id, step="other")


def test_no_billable_usage_releases_the_exact_reservation(db):
    session = db.session
    ns = world(session)
    result = authorize(session, ns)
    done = release_without_billable_usage(session, operation_id=result.operation_id)
    assert (done.charged_credits, done.released_credits, done.delivery_status) == (0, 36, "no_billable_usage")
    assert sums(session, ns.account) == (500, 0) and not entries(session, result.operation_id, "settlement")
    assert session.get(CreditReservation, result.reservation_id).state == "released"
    other = authorize(session, ns)
    call(session, other.operation_id, tokens=(10, 0))
    refused(session, AIBillingStateError, "usage was recorded", release_without_billable_usage,
            session, operation_id=other.operation_id)


# ---------------------------------------------------------------------------
# Delivery-based settlement (T-AI-04..10)
# ---------------------------------------------------------------------------

def test_delivered_response_settles_its_exact_usage_and_releases_the_rest(db):
    session = db.session
    ns = world(session)
    result = authorize(session, ns)
    call(session, result.operation_id)
    done = settle_delivered_operation(session, operation_id=result.operation_id, delivered_attempt_number=1)
    assert (done.charged_credits, done.released_credits, done.absorbed_credits) == (18, 18, 0)
    assert charged(session, result.operation_id) == 18
    assert sums(session, ns.account) == (500 - 18, 0)
    assert session.get(CreditReservation, result.reservation_id).state == "settled"
    before = row_counts(session)
    replay = settle_delivered_operation(session, operation_id=result.operation_id, delivered_attempt_number=1)
    assert replay.replay and replay.charged_credits == 18 and row_counts(session) == before


def test_fallback_charges_only_the_delivering_attempt_and_absorbs_the_failed_one(db):
    session = db.session
    ns = world(session)
    result = authorize(session, ns)
    call(session, result.operation_id, 1, outcome="timeout", tokens=(1000, 200), error="timeout")
    call(session, result.operation_id, 2, model=GEMINI, component="fallback")
    done = settle_delivered_operation(session, operation_id=result.operation_id, delivered_attempt_number=2)
    assert done.charged_credits == 6  # Gemini (1000*1 + 1000*5) / 1M * 1000; Claude never charged
    [row] = absorbed(session, result.operation_id)
    assert (row.reason, row.attempt_number, row.provider, row.fallback_attempted, row.fallback_outcome) == (
        "not_delivering_attempt", 1, "anthropic", True, "delivered")
    assert row.error_category == "timeout" and row.provider_request_ids_json == ["req-1-0"]
    assert row.absorbed_credits == 6 and row.provider_dispute_status == "none"


def test_tool_loop_calls_settle_together_and_the_tool_bound_is_typed(db):
    session = db.session
    ns = world(session)
    result = authorize(session, ns)
    for index in range(3):
        call(session, result.operation_id, 1, index, tokens=(500, 500),
             component="primary" if index == 0 else "tool_iteration")
    done = settle_delivered_operation(session, operation_id=result.operation_id, delivered_attempt_number=1)
    assert done.charged_credits == 27  # 3 * (500*3 + 500*15) / 1M * 1000, rounded once
    other = authorize(session, ns)
    with pytest.raises(RunawayLimitError) as error:
        call(session, other.operation_id, 1, RUNAWAY["max_tool_iterations"] + 1, component="tool_iteration")
    assert error.value.resumable and error.value.limit == "max_tool_iterations"
    with pytest.raises(RunawayLimitError, match="attempt bound"):
        call(session, other.operation_id, RUNAWAY["max_provider_attempts"] + 1)


def test_undelivered_response_charges_nothing_and_records_absorbed_evidence(db):
    session = db.session
    ns = world(session)
    result = authorize(session, ns)
    call(session, result.operation_id, 1, outcome="failed", tokens=(800, 0), error="provider_error")
    call(session, result.operation_id, 2, model=GEMINI, outcome="timeout", label="unknown", error="timeout")
    done = record_undelivered_operation(session, operation_id=result.operation_id)
    assert (done.charged_credits, done.delivery_status) == (0, "undelivered")
    assert sums(session, ns.account) == (500, 0) and not entries(session, result.operation_id, "settlement")
    first, second = absorbed(session, result.operation_id)
    assert (first.reason, first.usage_label, first.fallback_attempted, first.fallback_outcome) == (
        "undelivered", "reported", True, "undelivered")
    assert first.absorbed_credits == 3 and first.input_tokens == 800
    # A timeout is not assumed to have incurred provider charges.
    assert (second.usage_label, second.absorbed_cost_usd, second.absorbed_credits) == ("unknown", None, None)


def test_a_delivered_response_stays_charged_when_a_later_step_fails(db):
    session = db.session
    ns = world(session)
    result = authorize(session, ns)
    call(session, result.operation_id)
    settle_delivered_operation(session, operation_id=result.operation_id, delivered_attempt_number=1)
    refused(session, AIBillingStateError, "already recorded", record_undelivered_operation,
            session, operation_id=result.operation_id)
    refused(session, AIBillingStateError, "already recorded", settle_delivered_operation,
            session, operation_id=result.operation_id, delivered_attempt_number=2)
    assert charged(session, result.operation_id) == 18


@pytest.mark.parametrize("label", ["estimated", "unknown"])
def test_uncertain_usage_is_never_charged(db, label):
    session = db.session
    ns = world(session)
    result = authorize(session, ns)
    call(session, result.operation_id, label=label)
    done = settle_delivered_operation(session, operation_id=result.operation_id, delivered_attempt_number=1)
    assert done.charged_credits == 0 and sums(session, ns.account) == (500, 0)
    [row] = absorbed(session, result.operation_id)
    assert (row.reason, row.usage_label, row.delivery_status) == ("uncertain_usage", label, "delivered")


def test_usage_above_the_hold_uses_one_atomic_supplemental_reservation(db):
    session = db.session
    ns = world(session)
    result = authorize(session, ns)
    call(session, result.operation_id, tokens=(3000, 3000))  # 54 credits > 36 held
    done = settle_delivered_operation(session, operation_id=result.operation_id, delivered_attempt_number=1)
    assert (done.charged_credits, done.supplemental_credits, done.absorbed_credits) == (54, 18, 0)
    assert sums(session, ns.account) == (500 - 54, 0)
    keys = session.execute(sa.select(IdempotencyRegistry.key).where(
        IdempotencyRegistry.key.like(f"reservation:{result.operation_id}:2:%"))).scalars().all()
    assert len(keys) == 1


def test_a_failed_supplement_caps_the_charge_and_absorbs_the_excess(db):
    session = db.session
    ns = world(session, credits=40)
    result = authorize(session, ns)  # holds 36 of 40
    call(session, result.operation_id, tokens=(3000, 3000))  # 54 due; only 4 more exist
    done = settle_delivered_operation(session, operation_id=result.operation_id, delivered_attempt_number=1)
    assert (done.charged_credits, done.supplemental_credits, done.absorbed_credits) == (36, 0, 18)
    [row] = absorbed(session, result.operation_id)
    assert (row.reason, row.absorbed_credits) == ("above_reservation_cap", 18)
    # F2: the absorbed cost is only the part the capped charge did not recover (0.054 - 36/1000 USD).
    assert (Decimal(row.computed_cost_usd), Decimal(row.absorbed_cost_usd)) == (Decimal("0.054"), Decimal("0.018"))
    assert sums(session, ns.account) == (4, 0)


def test_quality_or_satisfaction_cannot_reach_settlement():
    import inspect
    parameters = set(inspect.signature(settle_delivered_operation).parameters)
    assert parameters == {"session", "operation_id", "delivered_attempt_number"}


def test_an_operation_cannot_record_calls_for_unauthorized_models_or_after_closing(db):
    session = db.session
    ns = world(session)
    result = authorize(session, ns, candidates=[CLAUDE])
    refused(session, UnpricedModelError, "not authorized", call, session, result.operation_id, model=GEMINI)
    release_without_billable_usage(session, operation_id=result.operation_id)
    refused(session, AIBillingStateError, "closed", call, session, result.operation_id)


# ---------------------------------------------------------------------------
# Expiry, checkpoints, and resume (T-AI-11..16, D23)
# ---------------------------------------------------------------------------

class Clock:
    """Moves the service's database clock (ORM schema only; the migrated tests use real time)."""

    def __init__(self, monkeypatch, start):
        self.now = _utc(start)
        monkeypatch.setattr(ai, "_clock", lambda _session: self.now)

    def at(self, start, seconds):
        self.now = _utc(start) + timedelta(seconds=seconds)
        return self.now


def test_f1_a_renewed_lease_settles_a_response_delivered_after_the_original_deadline(db, monkeypatch):
    """Founder decision 2026-11-16: verified delivered usage is billable after the original deadline."""
    session = db.session
    ns = world(session)
    result = authorize(session, ns)
    start, lease = _utc(result.expires_at) - timedelta(seconds=RUNAWAY["reservation_lease_seconds"]), \
        RUNAWAY["reservation_lease_seconds"]
    clock = Clock(monkeypatch, start)
    deadline = _utc(result.execution_deadline_at)
    assert deadline == start + timedelta(seconds=RUNAWAY["max_operation_seconds"])
    for seconds in range(100, RUNAWAY["max_operation_seconds"], 100):  # the worker keeps its hold alive
        clock.at(start, seconds)
        assert renew_ai_operation_reservation(session, operation_id=result.operation_id) == clock.now + timedelta(
            seconds=lease)
    clock.at(start, RUNAWAY["max_operation_seconds"] - 1)
    renew_ai_operation_reservation(session, operation_id=result.operation_id)
    call(session, result.operation_id)  # requested before the deadline; the response arrives later
    clock.at(start, RUNAWAY["max_operation_seconds"] + 60)
    refused(session, RunawayLimitError, "duration bound", check_provider_call, session,
            operation_id=result.operation_id, attempt_number=1, call_index=1, provider=CLAUDE[0], model=CLAUDE[1],
            max_input_tokens=1, max_output_tokens=1)  # no new call starts after the deadline
    renewed = renew_ai_operation_reservation(session, operation_id=result.operation_id)
    assert renewed == deadline + timedelta(seconds=lease)  # never past the deadline plus one lease period
    assert _utc(session.get(CreditReservation, result.reservation_id).expires_at) == renewed
    refused(session, AIBillingStateError, "still live", expire_ai_operation, session,
            operation_id=result.operation_id)  # a cleanup job cannot take a live hold
    done = settle_delivered_operation(session, operation_id=result.operation_id, delivered_attempt_number=1)
    assert (done.state, done.charged_credits, done.absorbed_credits) == ("finalized", 18, 0)
    assert sums(session, ns.account) == (500 - 18, 0) and not absorbed(session, result.operation_id)


@pytest.mark.parametrize("cleanup_first", [False, True], ids=["response_first", "cleanup_first"])
def test_f1_f4_a_response_after_the_lease_lapsed_is_kept_unbilled_whenever_cleanup_runs(
        db, monkeypatch, cleanup_first):
    """Founder decision 2026-11-17: a lapsed timer never costs the customer a successful response,
    and nothing is charged after the reservation's credits were released."""
    session = db.session
    ns = world(session)
    result = authorize(session, ns)
    call(session, result.operation_id, 1, outcome="failed", tokens=(100, 0))
    call(session, result.operation_id, 2)
    clock = Clock(monkeypatch, result.expires_at)  # the worker stopped renewing: the lease lapsed
    refused(session, ReservationLapsedError, "lapsed", renew_ai_operation_reservation, session,
            operation_id=result.operation_id)
    if cleanup_first:
        clock.at(result.expires_at, 3600)
        expired = expire_ai_operation(session, operation_id=result.operation_id)
        assert (expired.state, expired.delivery_status, expired.charged_credits, expired.released_credits) == (
            "expired", "unsettled", 0, 36)
    done = settle_delivered_operation(session, operation_id=result.operation_id, delivered_attempt_number=2)
    # The same end state whichever ran first: delivered, nothing charged, the hold released once.
    assert (done.state, done.delivery_status, done.charged_credits, done.supplemental_credits) == (
        "expired", "delivered", 0, 0)
    assert done.released_credits == (0 if cleanup_first else 36)
    assert session.get(AIBillingOperation, result.operation_id).delivered_attempt_number == 2
    assert session.get(CreditReservation, result.reservation_id).state == "expired"
    assert [(r.reason, r.delivery_status, r.attempt_number) for r in absorbed(session, result.operation_id)] == [
        ("reservation_expired", "unsettled", 1), ("reservation_expired", "unsettled", 2)]
    assert sums(session, ns.account) == (500, 0) and not entries(session, result.operation_id, "settlement")
    steps = session.execute(sa.select(AIOperationCheckpoint.step_key, AIOperationCheckpoint.charged_credits)
                            .where(AIOperationCheckpoint.operation_id == result.operation_id)).all()
    assert steps == [("step-1", 0)]  # the step reached the customer: a resume never repeats it
    # One outcome: replays agree, and every contradicting outcome is refused.
    assert settle_delivered_operation(session, operation_id=result.operation_id,
                                      delivered_attempt_number=2).replay
    assert expire_ai_operation(session, operation_id=result.operation_id).replay
    refused(session, AIBillingStateError, "already recorded", settle_delivered_operation, session,
            operation_id=result.operation_id, delivered_attempt_number=1)
    refused(session, AIBillingStateError, "already recorded", record_undelivered_operation, session,
            operation_id=result.operation_id)


def test_f4_an_expired_operation_keeps_late_evidence_and_records_one_answer_never_a_charge(db, monkeypatch):
    session = db.session
    ns = world(session)
    result = authorize(session, ns)
    clock = Clock(monkeypatch, result.expires_at)
    expire_ai_operation(session, operation_id=result.operation_id)
    clock.at(result.expires_at, 5)
    call(session, result.operation_id, 1, model=GEMINI, component="fallback")  # a late call: kept and absorbed
    assert [(r.reason, r.delivery_status, r.absorbed_credits) for r in absorbed(session, result.operation_id)] == [
        ("reservation_expired", "unsettled", 6)]
    assert session.get(AIBillingOperation, result.operation_id).absorbed_credits == 6
    refused(session, AIBillingStateError, "usage was recorded", release_without_billable_usage, session,
            operation_id=result.operation_id)
    done = record_undelivered_operation(session, operation_id=result.operation_id)
    assert (done.state, done.delivery_status, done.charged_credits, done.absorbed_credits) == (
        "expired", "undelivered", 0, 6)
    refused(session, AIBillingStateError, "already recorded", settle_delivered_operation, session,
            operation_id=result.operation_id, delivered_attempt_number=1)
    assert sums(session, ns.account) == (500, 0) and not entries(session, result.operation_id, "settlement")


def test_renewal_is_a_heartbeat_that_never_shortens_or_revives_a_lease(db, monkeypatch):
    session = db.session
    ns = world(session)
    result = authorize(session, ns)
    before = row_counts(session)
    first = renew_ai_operation_reservation(session, operation_id=result.operation_id)
    assert first >= _utc(result.expires_at) and row_counts(session) == before  # no ledger entry
    release_without_billable_usage(session, operation_id=result.operation_id)
    refused(session, AIBillingStateError, "closed", renew_ai_operation_reservation, session,
            operation_id=result.operation_id)


def test_phase6_expiry_of_a_held_lot_leaves_nothing_to_settle_and_the_usage_is_absorbed(db):
    """Upstream boundary: a hold never delays recurring expiry; settlement uses only what remains."""
    session = db.session
    ns = world(session)
    result = authorize(session, ns)
    call(session, result.operation_id)
    expire_recurring_credits(session, credit_period_id=ns.period.id, expired_at=_utc(ns.lot.expires_at),
                             delivery_obligations=DELIVERIES, **SERVICE)
    assert sums(session, ns.account) == (0, 0)
    done = settle_delivered_operation(session, operation_id=result.operation_id, delivered_attempt_number=1)
    assert (done.charged_credits, done.supplemental_credits, done.absorbed_credits) == (0, 0, 18)
    [row] = absorbed(session, result.operation_id)
    assert row.reason == "above_reservation_cap"
    assert not entries(session, result.operation_id, "settlement")


def test_resume_continues_from_the_last_settled_step_and_never_repeats_it(db):
    session = db.session
    ns = world(session)
    first = authorize(session, ns, step="research")
    call(session, first.operation_id)
    settle_delivered_operation(session, operation_id=first.operation_id, delivered_attempt_number=1)
    second = authorize(session, ns, step="draft", root_operation_id=first.operation_id,
                       resumed_from_operation_id=first.operation_id)
    call(session, second.operation_id, outcome="timeout", tokens=(400, 0), error="timeout")
    record_undelivered_operation(session, operation_id=second.operation_id)  # interrupted: not charged
    lineage = {"root_operation_id": first.operation_id, "resumed_from_operation_id": second.operation_id}
    refused(session, StepAlreadySettledError, "never repeated", authorize, session, ns, step="research", **lineage)
    resumed = authorize(session, ns, step="draft", **lineage)
    call(session, resumed.operation_id)
    settle_delivered_operation(session, operation_id=resumed.operation_id, delivered_attempt_number=1)
    steps = session.execute(sa.select(AIOperationCheckpoint.step_key, AIOperationCheckpoint.charged_credits)
                            .where(AIOperationCheckpoint.root_operation_id == first.operation_id)).all()
    assert sorted(steps) == [("draft", 18), ("research", 18)]
    assert sums(session, ns.account) == (500 - 36, 0)  # the interrupted attempt was absorbed, not charged
    assert [r.reason for r in absorbed(session, second.operation_id)] == ["undelivered"]


def test_a_concurrently_resumed_duplicate_step_is_absorbed_not_charged_twice(db):
    session = db.session
    ns = world(session)
    root = authorize(session, ns, step="root")
    release_without_billable_usage(session, operation_id=root.operation_id)
    lineage = {"root_operation_id": root.operation_id, "resumed_from_operation_id": root.operation_id}
    a, b = authorize(session, ns, step="s", **lineage), authorize(session, ns, step="s", **lineage)
    for result in (a, b):
        call(session, result.operation_id)
    assert settle_delivered_operation(session, operation_id=a.operation_id,
                                      delivered_attempt_number=1).charged_credits == 18
    duplicate = settle_delivered_operation(session, operation_id=b.operation_id, delivered_attempt_number=1)
    assert duplicate.charged_credits == 0
    assert [r.reason for r in absorbed(session, b.operation_id)] == ["step_already_settled"]


def test_a_running_operation_cannot_be_resumed_and_lineage_stays_in_one_account(db):
    session = db.session
    ns = world(session)
    running = authorize(session, ns, step="a")
    lineage = {"root_operation_id": running.operation_id, "resumed_from_operation_id": running.operation_id}
    refused(session, AIBillingStateError, "still running", authorize, session, ns, step="b", **lineage)
    other = account(session)
    capacity(session, [ns.tier, other.tier])
    release_without_billable_usage(session, operation_id=running.operation_id)
    refused(session, AIBillingIsolationError, "one billing account", authorize, session, other, step="b", **lineage)


# ---------------------------------------------------------------------------
# Capacity authorization (T-CAPACITY-01..12, D22)
# ---------------------------------------------------------------------------

def _denied(result, reason):
    assert result.outcome == "capacity_denied" and result.reason_code == reason
    assert result.held_credits == 0


def test_organization_window_denial_releases_the_reservation_and_charges_nothing(db):
    session = db.session
    ns = world(session, members=2, organization={"max_operations": 2})
    for user in ns.members:
        assert authorize(session, ns, user=user).outcome == "authorized"
    before = sums(session, ns.account)
    result = authorize(session, ns)
    _denied(result, "organization_window")
    assert result.available_again_at is not None and result.available_again_at > db_now(session)
    assert sums(session, ns.account) == before  # reserved and released atomically
    assert session.get(CreditReservation, result.reservation_id).state == "released"
    assert not entries(session, result.operation_id, "settlement")
    assert authorize(session, ns, result.operation_id).replay  # replay keeps the recorded denial


def test_member_window_stops_one_member_monopolizing_the_organization(db):
    session = db.session
    ns = world(session, members=2, member={"max_operations": 1})
    owner, teammate = ns.members
    assert authorize(session, ns, user=owner).outcome == "authorized"
    _denied(authorize(session, ns, user=owner), "member_window")
    assert authorize(session, ns, user=teammate).outcome == "authorized"


def test_member_limits_apply_within_each_organization_not_across_them(db):
    from app.models import OrganizationMember
    session = db.session
    ns = world(session, member={"max_operations": 1, "max_concurrent": 1})
    other = account(session)
    capacity(session, [ns.tier, other.tier], member={"max_operations": 1, "max_concurrent": 1})
    session.add(OrganizationMember(organization_id=other.org, user_id=ns.owner, role="collaborator",
                                   status="active"))
    session.flush()
    assert authorize(session, ns).outcome == "authorized"
    assert authorize(session, ns, org_id=other.org).outcome == "authorized"


@pytest.mark.parametrize("scope,reason", [("organization", "organization_concurrency"),
                                          ("member", "member_concurrency")])
def test_concurrency_limits_running_operations_until_one_finishes(db, scope, reason):
    session = db.session
    ns = world(session, **{scope: {"max_concurrent": 1}})
    running = authorize(session, ns)
    blocked = authorize(session, ns)
    _denied(blocked, reason)
    # The safe bound: a running lease can never be renewed past its deadline plus one lease period.
    assert _utc(blocked.available_again_at) == _utc(running.execution_deadline_at) + timedelta(
        seconds=RUNAWAY["reservation_lease_seconds"])
    release_without_billable_usage(session, operation_id=running.operation_id)
    assert authorize(session, ns).outcome == "authorized"


def test_provider_pressure_denies_only_when_every_candidate_is_unavailable(db):
    session = db.session
    ns = world(session)
    until = db_now(session) + timedelta(minutes=3)
    assert authorize(session, ns, unavailable_providers={"anthropic": until}).outcome == "authorized"
    result = authorize(session, ns, unavailable_providers={"anthropic": until, "google": until})
    _denied(result, "provider_pressure")
    assert _utc(result.available_again_at) == _utc(until)
    assert sums(session, ns.account) == (500 - 36, 36)  # only the first operation holds credits


def test_purchased_balance_never_bypasses_capacity_or_a_restriction(db):
    session = db.session
    ns = world(session, credits=100_000, organization={"max_operations": 1})
    assert authorize(session, ns).outcome == "authorized"
    _denied(authorize(session, ns), "organization_window")
    session.get(BillingAccount, ns.account).status = "restricted"
    session.flush()
    result = authorize(session, ns)
    _denied(result, "account_restricted")
    assert result.available_again_at is None  # abuse/safety details stay private


def test_the_highest_covered_tier_sets_priority(db):
    session = db.session
    ns = account(session)
    pricing(session)
    second = self_serve(session, ns, "month", credits=10, anchor=db_now(session) - timedelta(hours=1))
    higher = tier_key(session, second)
    capacity(session, [ns.tier, higher], priorities={ns.tier: 1, higher: 5})
    result = authorize(session, ns)
    assert (result.tier_key, result.priority) == (higher, 5)


# ---------------------------------------------------------------------------
# Individual fair use inside shared-credit organizations (founder decision 2026-11-16)
# ---------------------------------------------------------------------------

def test_every_member_has_their_own_allowance_and_all_draw_on_the_shared_balance(db):
    session = db.session
    ns = world(session, members=3, member={"max_operations": 1}, without_organization=True)
    for user in ns.members:
        assert authorize(session, ns, user=user).outcome == "authorized"
    for user in ns.members:  # one member's use never spends another member's allowance
        _denied(authorize(session, ns, user=user), "member_window")
    assert sums(session, ns.account) == (500 - 3 * 36, 3 * 36)  # one organization pool funds every member


def test_a_single_member_organization_follows_the_same_individual_rules(db):
    session = db.session
    ns = world(session, members=1, member={"max_operations": 1}, without_organization=True)
    assert authorize(session, ns).outcome == "authorized"
    _denied(authorize(session, ns), "member_window")


def test_token_windows_measure_delivered_verified_usage_never_credits_or_lost_work(db):
    session = db.session
    windows = [{"key": "five_hour", "window_seconds": 5 * 3600, "max_tokens": 3000},
               {"key": "weekly", "window_seconds": 7 * 86400, "max_operations": 100}]
    ns = world(session, members=2, credits=100_000, member_windows=windows)
    owner, teammate = ns.members
    first = authorize(session, ns, user=owner)
    call(session, first.operation_id, 1, tokens=(5000, 0))  # an answer that was retried, never delivered
    call(session, first.operation_id, 2, model=GEMINI, component="fallback")  # 2000 tokens, delivered
    settle_delivered_operation(session, operation_id=first.operation_id, delivered_attempt_number=2)
    settle_delivered_operation(session, operation_id=first.operation_id, delivered_attempt_number=2)  # replay
    lost = authorize(session, ns, user=owner)
    call(session, lost.operation_id, tokens=(9000, 0))  # answered, but it never reached the member
    record_undelivered_operation(session, operation_id=lost.operation_id)
    guessed = authorize(session, ns, user=owner)
    call(session, guessed.operation_id, label="estimated", tokens=(9000, 0))  # delivered, usage not verified
    settle_delivered_operation(session, operation_id=guessed.operation_id, delivered_attempt_number=1)
    second = authorize(session, ns, user=owner)
    call(session, second.operation_id)
    settle_delivered_operation(session, operation_id=second.operation_id, delivered_attempt_number=1)
    first_call = session.execute(sa.select(AIProviderCallUsage).where(
        AIProviderCallUsage.operation_id == first.operation_id, AIProviderCallUsage.attempt_number == 2)
    ).scalar_one()
    blocked = authorize(session, ns, user=owner)  # 4000 tokens >= 3000, though 100,000 credits remain
    _denied(blocked, "member_window")
    decision = session.execute(sa.select(AICapacityDecision).where(
        AICapacityDecision.operation_id == blocked.operation_id)).scalar_one()
    assert decision.evidence_json["denied_window"] == "five_hour"
    assert decision.evidence_json["member_window:five_hour"]["tokens"] == 4000
    assert _utc(blocked.available_again_at) == _utc(first_call.recorded_at) + timedelta(hours=5)
    assert authorize(session, ns, user=teammate).outcome == "authorized"


def test_a_window_can_bound_tokens_of_listed_models_only(db):
    session = db.session
    windows = [{"key": "claude_five_hour", "window_seconds": 5 * 3600, "max_tokens": 1000,
                "models": [list(CLAUDE)]}]
    ns = world(session, member_windows=windows)
    first = authorize(session, ns, candidates=[CLAUDE])
    call(session, first.operation_id)
    settle_delivered_operation(session, operation_id=first.operation_id, delivered_attempt_number=1)
    _denied(authorize(session, ns, candidates=[CLAUDE]), "member_window")
    assert authorize(session, ns, candidates=[GEMINI]).outcome == "authorized"


def test_failed_and_undelivered_requests_still_count_toward_request_limits(db):
    """Abuse and capacity controls are not billing: lost work is never charged, but it still counts."""
    session = db.session
    ns = world(session, members=1, member={"max_operations": 2}, without_organization=True)
    first = authorize(session, ns)
    call(session, first.operation_id, outcome="failed", tokens=(100, 0))
    record_undelivered_operation(session, operation_id=first.operation_id)
    second = authorize(session, ns)
    call(session, second.operation_id, outcome="timeout", tokens=(0, 0))
    record_undelivered_operation(session, operation_id=second.operation_id)
    _denied(authorize(session, ns), "member_window")
    assert sums(session, ns.account) == (500, 0)
    assert not entries(session, first.operation_id, "settlement") and not entries(
        session, second.operation_id, "settlement")


@pytest.mark.parametrize("tier_rules,match", [
    ({"priority": 1, "member": {"max_concurrent": 1}}, "at least one usage window"),
    ({"priority": 1, "member": {"max_concurrent": 1, "windows": [{"key": "w", "window_seconds": 60}]}},
     "bound operations or tokens"),
    ({"priority": 1, "member": {"windows": [{"key": "w", "window_seconds": 60, "max_operations": 1}]}},
     "max_concurrent"),
    ({"priority": 1, "member": {"max_concurrent": 1, "windows": [
        {"key": "w", "window_seconds": 60, "max_operations": 1, "models": [list(CLAUDE)]}]}},
     "only its token bound"),
    ({"priority": 1, "organization": {}, "member": {"max_concurrent": 1, "windows": [
        {"key": "w", "window_seconds": 60, "max_operations": 1}]}}, "must bound something"),
])
def test_fair_use_policy_without_an_individual_allowance_fails_closed(tier_rules, match):
    rules = {"schema": "jaspen.capacity.v1", "tiers": {"plan": tier_rules}, "runaway": RUNAWAY}
    with pytest.raises(CapacityPolicyRequiredError, match=match):
        ai.capacity_rules(Ns(rules_json=rules))


@pytest.mark.parametrize("name", sorted(RUNAWAY))
def test_capacity_policy_requires_every_runaway_bound(name):
    tiers = {"plan": {"priority": 1, "member": {"max_concurrent": 1, "windows": [WINDOW]}}}
    runaway = {k: v for k, v in RUNAWAY.items() if k != name}
    assert ai.capacity_rules(Ns(rules_json={"schema": "jaspen.capacity.v1", "tiers": tiers, "runaway": RUNAWAY}))
    with pytest.raises(CapacityPolicyRequiredError, match=name):
        ai.capacity_rules(Ns(rules_json={"schema": "jaspen.capacity.v1", "tiers": tiers, "runaway": runaway}))


# ---------------------------------------------------------------------------
# Runaway bounds and context growth (F6, D22)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("max_in,max_out,limit", [
    (9000, 10, "max_call_input_tokens"), (10, 9000, "max_call_output_tokens"),
])
def test_f6_a_request_above_a_per_call_token_bound_is_refused_before_any_write(db, max_in, max_out, limit):
    session = db.session
    ns = world(session, runaway={"max_reserved_credits": 100_000})
    op_id = operation(session, ns)
    before = row_counts(session)
    with pytest.raises(RunawayLimitError) as error:
        authorize(session, ns, op_id, max_in=max_in, max_out=max_out)
    assert error.value.limit == limit and error.value.resumable and row_counts(session) == before


def test_f6_context_growth_stops_at_the_operation_token_bound_with_a_typed_outcome(db):
    session = db.session
    ns = world(session, runaway={"max_operation_tokens": 10_000})
    result = authorize(session, ns)
    check = dict(operation_id=result.operation_id, attempt_number=1, provider=CLAUDE[0], model=CLAUDE[1],
                 max_output_tokens=1000)
    before = row_counts(session)
    for index, context in enumerate((2000, 3000)):  # each tool iteration carries a larger context
        assert check_provider_call(session, call_index=index, max_input_tokens=context, **check)
        call(session, result.operation_id, 1, index, tokens=(context, 1000),
             component="primary" if index == 0 else "tool_iteration")
    assert row_counts(session)["ai_provider_call_usage"] == before["ai_provider_call_usage"] + 2
    with pytest.raises(RunawayLimitError) as error:
        check_provider_call(session, call_index=2, max_input_tokens=3500, **check)  # 7000 + 4500 > 10000
    assert error.value.limit == "max_operation_tokens" and error.value.resumable
    for kwargs, limit in (({"call_index": 2, "max_input_tokens": 9000}, "max_call_input_tokens"),
                          ({"call_index": 5, "max_input_tokens": 10}, "max_tool_iterations")):
        with pytest.raises(RunawayLimitError) as error:
            check_provider_call(session, **{**check, **kwargs})
        assert error.value.limit == limit
    refused(session, AIBillingConflictError, "already recorded", check_provider_call, session,
            call_index=1, max_input_tokens=10, **check)


# ---------------------------------------------------------------------------
# Exact arithmetic (F5)
# ---------------------------------------------------------------------------

def test_f5_settlement_uses_exact_token_costs_without_premature_rounding(db):
    session = db.session
    ns = account(session)
    # A 10-decimal rate whose cost needs 16 decimals; rounding it to 10 would settle 3 credits, not 4.
    pricing(session, rates={CLAUDE: ("3.0000000001", "1")}, conversion="1000000")
    capacity(session, [ns.tier])
    result = authorize_ai_operation(
        session, operation_id=operation(session, ns), actor_user_id=ns.owner, step_key="s", candidates=[CLAUDE],
        max_input_tokens=1, max_output_tokens=1)
    assert result.required_credits == 5  # ceil(3.0000000001 + 1)
    call(session, result.operation_id, tokens=(1, 0))
    done = settle_delivered_operation(session, operation_id=result.operation_id, delivered_attempt_number=1)
    assert done.charged_credits == 4  # ceil(0.0000030000000001 USD * 1,000,000)
    assert ai._cost(Ns(input_rate=Decimal("3.0000000001"), output_rate=Decimal("1")), 1, 0) == Decimal(
        "0.0000030000000001")
    if session.get_bind().dialect.name == "postgresql":  # SQLite stores numerics approximately
        usage = session.execute(sa.select(AIProviderCallUsage)).scalar_one()
        assert Decimal(usage.computed_cost_usd) == Decimal("0.0000030000000001")


def test_f5_the_tool_loop_is_rounded_once_not_per_call(db):
    session = db.session
    ns = world(session)
    result = authorize(session, ns)
    for index in range(3):  # each call alone is 0.3 credits
        call(session, result.operation_id, 1, index, tokens=(100, 0),
             component="primary" if index == 0 else "tool_iteration")
    done = settle_delivered_operation(session, operation_id=result.operation_id, delivered_attempt_number=1)
    assert done.charged_credits == 1  # ceil(0.9), not 3 * ceil(0.3)


# ---------------------------------------------------------------------------
# Tenant isolation and eligibility
# ---------------------------------------------------------------------------

def test_operations_are_isolated_between_organizations_and_members(db):
    session = db.session
    ns, other = world(session), account(session)
    outsider = other.owner
    refused(session, AIBillingIsolationError, "another member", authorize_ai_operation, session,
            operation_id=operation(session, ns), actor_user_id=outsider, step_key="s", candidates=[CLAUDE],
            max_input_tokens=1, max_output_tokens=1)
    foreign = operation(session, ns, outsider)  # an outsider's operation claiming this organization
    refused(session, AIBillingIsolationError, "not an active member", authorize, session, ns, foreign, outsider)
    op_id = operation(session, ns)
    session.get(AIOperation, op_id).billing_account_id = other.account
    session.flush()
    refused(session, AIBillingIsolationError, "another billing account", authorize, session, ns, op_id)


def test_lots_attributed_to_another_member_or_scoped_lots_are_not_spendable(db):
    session = db.session
    ns = world(session, members=2, credits=10)
    teammate = ns.members[1]
    now = db_now(session)
    for attribution, scope in ((teammate, None), (None, {"scope": "unapproved"})):
        lot = CreditLot(billing_account_id=ns.account, source_type="internal", source_id=uuid.uuid4().hex,
                        member_attribution_id=attribution, eligibility_scope=scope, original_amount=1000,
                        available_at=now - timedelta(minutes=1), origin_evidence_json={"fixture": True})
        session.add(lot)
        session.flush()
        ai._append(session, op=Ns(billing_account_id=ns.account, operation_id=None), lot_id=lot.id,
                   entry_type="grant", available=1000, held=0, reservation_id=None, related_entry_id=None,
                   key=f"fixture-grant:{lot.id}", at=now, reason="fixture", evidence={})
    assert authorize(session, ns).outcome == "credit_exhausted"  # 10 pool credits < 36
    assert authorize(session, ns, user=teammate).outcome == "authorized"  # their attributed lot


def test_phase12_service_has_no_live_runtime_callers():
    app_dir = BACKEND_DIR / "app"
    callers = [
        str(path.relative_to(BACKEND_DIR)) for path in app_dir.rglob("*.py")
        # Phase 13 projections are themselves inactive and only read Phase 12 records; the inactive Phase 14
        # backfill reads only the pricing conversion key to verify the internal-unit rate.
        if path.name not in {"billing_ai_operations.py", "billing_reliable_delivery.py",
                             "models_billing_phase12.py", "models.py", "billing_projections.py",
                             "billing_migration.py",
                             "billing_shadow.py"}  # Phase 16 shadow comparison is inactive and read only
        and ("billing_ai_operations" in path.read_text() or "models_billing_phase12" in path.read_text())
    ]
    assert callers == []


# ---------------------------------------------------------------------------
# Migration: single head, SQLite parity, guards, downgrade safety
# ---------------------------------------------------------------------------

def _revision():
    return ScriptDirectory(MIGRATIONS_DIR).get_revision(REVISION).module


@contextlib.contextmanager
def _ops(engine):
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            yield connection


def test_revision_extends_phase11_and_is_single_head():
    script = ScriptDirectory(MIGRATIONS_DIR)
    # Phase 14 (d2f4a6c8e0b3) is the next revision; Phase 12 stays its direct parent.
    assert script.get_revision("d2f4a6c8e0b3").down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PARENT


def _assert_models_match(engine):
    from app import models_billing_phase12 as phase12
    inspector = sa.inspect(engine)
    for model in (phase12.AIBillingOperation, phase12.AICapacityDecision, phase12.AIProviderCallUsage,
                  phase12.AIAbsorbedUsage, phase12.AIOperationCheckpoint):
        table = model.__table__
        assert {c.name for c in table.columns} == {c["name"] for c in inspector.get_columns(table.name)}
        assert {c.name for c in table.constraints if isinstance(c, sa.CheckConstraint)} == {
            c["name"] for c in inspector.get_check_constraints(table.name)}, table.name
        assert {c.name for c in table.constraints if isinstance(c, sa.UniqueConstraint)} == {
            c["name"] for c in inspector.get_unique_constraints(table.name)}, table.name
        assert {i.name for i in table.indexes} <= {i["name"] for i in inspector.get_indexes(table.name)}


def test_sqlite_migration_matches_models_guards_and_downgrade_is_safe(tmp_path):
    module = _revision()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase12.sqlite'}")
    try:
        tables = [t for t in flask_db.metadata.sorted_tables if t.name not in PHASE12_TABLES]
        flask_db.metadata.create_all(engine, tables=tables)
        with _ops(engine):
            module.upgrade()
        _assert_models_match(engine)
        with engine.connect() as connection:
            names = set(connection.execute(sa.text("SELECT name FROM sqlite_master WHERE type='trigger'")).scalars())
        assert set(module.SQLITE_TRIGGERS) <= names
        with engine.begin() as connection:
            connection.execute(sa.text("PRAGMA foreign_keys=OFF"))
            connection.execute(sa.text(
                "INSERT INTO ai_operation_checkpoints (id,root_operation_id,step_key,operation_id,charged_credits,"
                "completed_at) VALUES ('c1','r','s','o',3,'2026-11-16')"))
            for statement in ("UPDATE ai_operation_checkpoints SET charged_credits=0",
                              "DELETE FROM ai_operation_checkpoints"):
                with pytest.raises(sa.exc.DBAPIError, match="immutable"):
                    connection.execute(sa.text(statement))
            # A settlement needs a delivered, finalized Phase 12 operation.
            with pytest.raises(sa.exc.DBAPIError, match="delivered"):
                connection.execute(sa.text(
                    "INSERT INTO credit_ledger_entries (id,billing_account_id,lot_id,entry_type,available_delta,"
                    "held_delta,reservation_id,operation_id,related_entry_id,idempotency_registry_id,effective_at,"
                    "created_at,actor_type,actor_id,reason_code,evidence_json) VALUES ('e','a','l','settlement',0,"
                    "-1,'r','o','x','i','2026-11-16','2026-11-16','system','t','t','{}')"))
        with pytest.raises(module.Phase12EvidenceNotEmptyError):
            with _ops(engine):
                module.downgrade()
        with engine.begin() as connection:
            connection.execute(sa.text("DROP TRIGGER trg_phase12_checkpoints_delete"))
            connection.execute(sa.text("DELETE FROM ai_operation_checkpoints"))
        with _ops(engine):
            module.downgrade()
        assert not set(sa.inspect(engine).get_table_names()) & set(PHASE12_TABLES)
        with engine.connect() as connection:
            names = set(connection.execute(sa.text("SELECT name FROM sqlite_master WHERE type='trigger'")).scalars())
        assert not set(module.SQLITE_TRIGGERS) & names
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# PostgreSQL: fully migrated database, every guard live
# ---------------------------------------------------------------------------

def _migrated_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("local disposable PostgreSQL is not configured")
    engine = sa.create_engine(url, pool_size=12, max_overflow=4)
    with engine.connect() as connection:
        revision = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    if revision not in {REVISION, "d2f4a6c8e0b3", "f3a5c7e9b1d2", "c8a9989843b5", "a1f3c5e7b9d0", "e7b9d1f3a5c6"}:
        engine.dispose()
        pytest.fail(f"Phase 12 migrated tests require Alembic head {REVISION} or Phase 14; found {revision!r}")
    return engine


@contextlib.contextmanager
def migrated_session(engine, isolation="READ COMMITTED"):
    with Session(engine.execution_options(isolation_level=isolation), expire_on_commit=False) as session:
        yield session


def _pg_world(engine, *, credits=500, **capacity_overrides):
    with migrated_session(engine) as session:
        ns = world(session, credits=credits, **capacity_overrides)
        session.commit()
        return ns


@PG
def test_postgres_migrated_lifecycle_passes_every_guard():
    engine = _migrated_engine()
    try:
        ns = _pg_world(engine)
        with migrated_session(engine) as session:
            first = authorize(session, ns)
            session.commit()
            call(session, first.operation_id, 1, outcome="timeout", tokens=(100, 0), error="timeout")
            call(session, first.operation_id, 2, model=GEMINI, tokens=(3000, 9000), component="fallback")
            session.commit()
            done = settle_delivered_operation(session, operation_id=first.operation_id, delivered_attempt_number=2)
            session.commit()
            assert (done.charged_credits, done.supplemental_credits) == (48, 12)
            second = authorize(session, ns)
            session.commit()
            record_undelivered_operation(session, operation_id=second.operation_id)
            session.commit()
            third = authorize(session, ns)
            session.commit()
            release_without_billable_usage(session, operation_id=third.operation_id)
            session.commit()
            assert sums(session, ns.account) == (500 - 48, 0)
    finally:
        engine.dispose()


@PG
@pytest.mark.parametrize("statement,message", [
    ("UPDATE ai_provider_call_usage SET input_tokens=1 WHERE operation_id=:op", "immutable"),
    ("DELETE FROM ai_capacity_decisions WHERE operation_id=:op", "immutable"),
    ("UPDATE ai_absorbed_usage SET absorbed_credits=0 WHERE operation_id=:op", "immutable"),
    ("UPDATE ai_operation_checkpoints SET charged_credits=0 WHERE operation_id=:op", "immutable"),
    ("UPDATE ai_billing_operations SET charged_credits=0 WHERE operation_id=:op", "finalized"),
    ("UPDATE ai_billing_operations SET pricing_policy_version_id=pricing_policy_version_id||'' "
     "WHERE operation_id=:op", "immutable"),
])
def test_postgres_migrated_direct_sql_cannot_rewrite_ai_billing_evidence(statement, message):
    engine = _migrated_engine()
    try:
        ns = _pg_world(engine)
        with migrated_session(engine) as session:
            result = authorize(session, ns)
            call(session, result.operation_id, 1, outcome="failed", tokens=(10, 0))
            call(session, result.operation_id, 2)
            settle_delivered_operation(session, operation_id=result.operation_id, delivered_attempt_number=2)
            session.commit()
        with engine.connect() as connection:
            with pytest.raises(sa.exc.DBAPIError, match=message):
                connection.execute(sa.text(statement), {"op": result.operation_id})
            connection.rollback()
    finally:
        engine.dispose()


@PG
def test_postgres_migrated_guards_refuse_unbound_reservations_and_undelivered_settlements():
    engine = _migrated_engine()
    try:
        ns = _pg_world(engine)
        with migrated_session(engine) as session:
            result = authorize(session, ns)
            session.commit()
            loose = operation(session, ns)
            session.commit()
            [hold] = entries(session, result.operation_id, "reservation")
        with engine.connect() as connection:
            registry = lambda key: connection.execute(sa.text(
                "INSERT INTO idempotency_registry (id,namespace,key,request_fingerprint,state,claimed_at) "
                "VALUES (:k,'phase12-bypass',:k,:f,'claimed',now())"), {"k": key, "f": "b" * 64})
            res_id = str(uuid.uuid4())
            registry(res_id)
            with pytest.raises(sa.exc.DBAPIError, match="Phase 12 operation binding"):
                connection.execute(sa.text(
                    "UPDATE ai_operations SET billing_account_id=:a, pricing_policy_version_id=:p WHERE id=:o"
                    ), {"a": ns.account, "p": ns.pricing.id, "o": loose})
                connection.execute(sa.text(
                    "INSERT INTO credit_reservations (id,billing_account_id,operation_id,pricing_policy_version_id,"
                    "capacity_policy_version_id,idempotency_registry_id,requested_amount,authorized_amount,state,"
                    "request_fingerprint,created_at,expires_at) VALUES (:id,:a,:o,:p,:c,:r,5,5,'reserved',:f,now(),"
                    "now()+interval '1 hour')"), {"id": res_id, "a": ns.account, "o": loose,
                                                  "p": ns.pricing.id, "c": ns.capacity.id,
                                                  "r": res_id, "f": "b" * 64})
            connection.rollback()
        set_id = str(uuid.uuid4())
        with engine.connect() as connection:
            connection.execute(sa.text(
                "INSERT INTO idempotency_registry (id,namespace,key,request_fingerprint,state,claimed_at) "
                "VALUES (:k,'phase12-bypass',:k,:f,'claimed',now())"), {"k": set_id, "f": "c" * 64})
            with pytest.raises(sa.exc.DBAPIError, match="delivered"):
                connection.execute(sa.text(
                    "INSERT INTO credit_ledger_entries (id,billing_account_id,lot_id,entry_type,available_delta,"
                    "held_delta,reservation_id,operation_id,related_entry_id,idempotency_registry_id,effective_at,"
                    "created_at,actor_type,actor_id,reason_code,evidence_json) VALUES (:id,:a,:l,'settlement',0,-1,"
                    ":r,:o,:e,:k,now(),now(),'system','bypass','bypass','{}')"),
                    {"id": set_id, "k": set_id, "a": ns.account, "l": hold.lot_id,
                     "r": result.reservation_id, "o": result.operation_id, "e": hold.id})
            connection.rollback()
    finally:
        engine.dispose()


@PG
def test_postgres_migrated_binding_requires_an_effective_pricing_version():
    engine = _migrated_engine()
    try:
        ns = _pg_world(engine)
        with migrated_session(engine) as session:
            draft = PricingPolicyVersion(
                version=f"phase12-draft-{uuid.uuid4().hex[:8]}", state="draft", credit_conversion_version="t",
                rounding_rule="ceil_whole_credit", conversion_json={}, customer_credit_impact=False,
                notice_required=False)
            session.add(draft)
            session.commit()
            result = authorize(session, ns)
            session.commit()
        with engine.connect() as connection:
            with pytest.raises(sa.exc.DBAPIError, match="immutable"):
                connection.execute(sa.text("UPDATE ai_billing_operations SET pricing_policy_version_id=:d "
                                           "WHERE operation_id=:o"), {"d": draft.id, "o": result.operation_id})
            connection.rollback()
    finally:
        engine.dispose()


@PG
def test_postgres_migrated_commands_require_read_committed():
    engine = _migrated_engine()
    try:
        ns = _pg_world(engine)
        for level in ("REPEATABLE READ", "SERIALIZABLE"):
            with migrated_session(engine, level) as session:
                with pytest.raises(ai.AIBillingIsolationLevelError):
                    authorize(session, ns)
                session.rollback()
    finally:
        engine.dispose()


@PG
def test_postgres_concurrent_authorizations_never_overcommit_the_balance():
    engine = _migrated_engine()
    try:
        ns = _pg_world(engine, credits=100)  # room for two 36-credit holds, not three
        with migrated_session(engine) as session:
            ops = [operation(session, ns) for _ in range(6)]
            session.commit()
        barrier = threading.Barrier(len(ops))

        def run(op_id):
            with migrated_session(engine) as session:
                barrier.wait()
                outcome = authorize(session, ns, op_id).outcome
                session.commit()
                return outcome

        with ThreadPoolExecutor(len(ops)) as pool:
            outcomes = list(pool.map(run, ops))
        assert sorted(outcomes) == ["authorized"] * 2 + ["credit_exhausted"] * 4
        with migrated_session(engine) as session:
            assert sums(session, ns.account) == (100 - 72, 72)
    finally:
        engine.dispose()


@PG
def test_postgres_concurrent_window_authorizations_respect_the_organization_limit():
    engine = _migrated_engine()
    try:
        ns = _pg_world(engine, organization={"max_operations": 3})
        with migrated_session(engine) as session:
            ops = [operation(session, ns) for _ in range(6)]
            session.commit()
        barrier = threading.Barrier(len(ops))

        def run(op_id):
            with migrated_session(engine) as session:
                barrier.wait()
                outcome = authorize(session, ns, op_id).outcome
                session.commit()
                return outcome

        with ThreadPoolExecutor(len(ops)) as pool:
            outcomes = list(pool.map(run, ops))
        assert sorted(outcomes) == ["authorized"] * 3 + ["capacity_denied"] * 3
    finally:
        engine.dispose()


@PG
def test_postgres_concurrent_settlement_replays_converge_to_one_charge():
    engine = _migrated_engine()
    try:
        ns = _pg_world(engine)
        with migrated_session(engine) as session:
            result = authorize(session, ns)
            call(session, result.operation_id)
            session.commit()
        barrier = threading.Barrier(4)

        def run(_index):
            with migrated_session(engine) as session:
                barrier.wait()
                done = settle_delivered_operation(session, operation_id=result.operation_id,
                                                  delivered_attempt_number=1)
                session.commit()
                return done.replay

        with ThreadPoolExecutor(4) as pool:
            replays = list(pool.map(run, range(4)))
        assert sorted(replays) == [False, True, True, True]
        with migrated_session(engine) as session:
            assert charged(session, result.operation_id) == 18
            assert sums(session, ns.account) == (500 - 18, 0)
    finally:
        engine.dispose()


def _settlement_sql(connection, ns, result, hold, *, held, evidence):
    entry_id = str(uuid.uuid4())
    connection.execute(sa.text(
        "INSERT INTO idempotency_registry (id,namespace,key,request_fingerprint,state,claimed_at) "
        "VALUES (:k,'phase12-bypass',:k,:f,'claimed',now())"), {"k": entry_id, "f": "d" * 64})
    connection.execute(sa.text(
        "INSERT INTO credit_ledger_entries (id,billing_account_id,lot_id,entry_type,available_delta,"
        "held_delta,reservation_id,operation_id,related_entry_id,idempotency_registry_id,effective_at,"
        "created_at,actor_type,actor_id,reason_code,evidence_json) VALUES (:id,:a,:l,'settlement',0,:h,"
        ":r,:o,:e,:k,now(),now(),'system','bypass','bypass',CAST(:ev AS json))"),
        {"id": entry_id, "k": entry_id, "a": ns.account, "l": hold.lot_id, "h": -held, "ev": evidence,
         "r": result.reservation_id, "o": result.operation_id, "e": hold.id})


@PG
def test_postgres_f7_a_settlement_is_tied_to_the_delivering_attempt_and_its_priced_usage():
    engine = _migrated_engine()
    try:
        ns = _pg_world(engine)
        with migrated_session(engine) as session:
            result = authorize(session, ns)
            call(session, result.operation_id, 1, outcome="failed", tokens=(10, 0))
            call(session, result.operation_id, 2, model=GEMINI, component="fallback")  # 6 credits due
            session.commit()
            [hold] = entries(session, result.operation_id, "reservation")
        cases = (
            (1, '{"delivered_attempt_number": 1}', "delivered attempt"),  # the failed attempt delivered nothing
            (1, '{}', "delivered attempt"),
            (7, '{"delivered_attempt_number": 2}', "priced usage"),  # more than the attempt's usage
        )
        for held, evidence, message in cases:
            with engine.connect() as connection:
                with pytest.raises(sa.exc.DBAPIError, match=message):
                    _settlement_sql(connection, ns, result, hold, held=held, evidence=evidence)
                connection.rollback()
        with engine.connect() as connection:  # exactly the priced usage passes every guard
            _settlement_sql(connection, ns, result, hold, held=6, evidence='{"delivered_attempt_number": 2}')
            connection.rollback()
    finally:
        engine.dispose()


@PG
@pytest.mark.parametrize("statement,message", [
    ("UPDATE ai_billing_operations SET expires_at = expires_at - interval '1 second' WHERE operation_id=:op",
     "renewed only forward"),
    ("UPDATE ai_billing_operations SET expires_at = execution_deadline_at + interval '1 day' "
     "WHERE operation_id=:op", "renewed only forward"),
    ("UPDATE ai_billing_operations SET state='expired', finalized_at=now(), delivery_status='undelivered', "
     "charged_credits=0, absorbed_credits=0 WHERE operation_id=:op", "lease lapsed"),
    ("UPDATE ai_billing_operations SET lease_seconds = lease_seconds + 1 WHERE operation_id=:op", "immutable"),
    ("UPDATE ai_billing_operations SET max_operation_tokens = max_operation_tokens + 1 WHERE operation_id=:op",
     "immutable"),
])
def test_postgres_migrated_lease_and_bounds_cannot_be_rewritten(statement, message):
    engine = _migrated_engine()
    try:
        ns = _pg_world(engine)
        with migrated_session(engine) as session:
            result = authorize(session, ns)
            session.commit()
        with engine.connect() as connection:
            with pytest.raises(sa.exc.DBAPIError, match=message):
                connection.execute(sa.text(statement), {"op": result.operation_id})
            connection.rollback()
    finally:
        engine.dispose()


SHORT_LEASE = {"max_operation_seconds": 1, "reservation_lease_seconds": 2}


@PG
def test_postgres_an_expired_operation_records_one_delivery_answer_and_never_a_charge():
    """Founder decision 2026-11-17, enforced by the migrated guard as well as the service."""
    import time
    engine = _migrated_engine()
    try:
        ns = _pg_world(engine, runaway=SHORT_LEASE)
        with migrated_session(engine) as session:
            result = authorize(session, ns)
            call(session, result.operation_id)
            session.commit()
        with migrated_session(engine) as session:
            time.sleep(max(0.0, (_utc(result.expires_at) - db_now(session)).total_seconds() + 0.1))
            assert expire_ai_operation(session, operation_id=result.operation_id).delivery_status == "unsettled"
            session.commit()
        refusals = [
            ("UPDATE ai_billing_operations SET charged_credits = 1 WHERE operation_id=:op", "never charged"),
            ("UPDATE ai_billing_operations SET delivery_status = 'delivered', delivered_attempt_number = 2 "
             "WHERE operation_id=:op", "successful call"),
            ("UPDATE ai_billing_operations SET state = 'finalized', delivery_status = 'delivered', "
             "delivered_attempt_number = 1, charged_credits = 18 WHERE operation_id=:op", "never charged"),
        ]
        for statement, message in refusals:
            with engine.connect() as connection:
                with pytest.raises(sa.exc.DBAPIError, match=message):
                    connection.execute(sa.text(statement), {"op": result.operation_id})
                connection.rollback()
        with migrated_session(engine) as session:
            done = settle_delivered_operation(session, operation_id=result.operation_id, delivered_attempt_number=1)
            assert (done.state, done.delivery_status, done.charged_credits) == ("expired", "delivered", 0)
            session.commit()
        with engine.connect() as connection:  # the answer is recorded once
            with pytest.raises(sa.exc.DBAPIError, match="never charged"):
                connection.execute(sa.text(
                    "UPDATE ai_billing_operations SET delivery_status = 'undelivered', "
                    "delivered_attempt_number = NULL WHERE operation_id=:op"), {"op": result.operation_id})
            connection.rollback()
        with migrated_session(engine) as session:
            assert charged(session, result.operation_id) == 0 and sums(session, ns.account) == (500, 0)
    finally:
        engine.dispose()


@PG
def test_postgres_f8_settlement_racing_expiration_has_exactly_one_outcome():
    import time
    engine = _migrated_engine()
    try:
        ns = _pg_world(engine, runaway=SHORT_LEASE)
        results = []
        for _ in range(6):  # staggered leases, so the race straddles the lease boundary
            with migrated_session(engine) as session:
                results.append(authorize(session, ns))
                call(session, results[-1].operation_id)
                session.commit()
            time.sleep(0.3)
        with migrated_session(engine) as session:
            delay = (_utc(results[2].expires_at) - db_now(session)).total_seconds() - 0.05
        time.sleep(max(0.0, delay))  # earlier leases have lapsed (expiry wins), later ones are live
        barrier = threading.Barrier(2 * len(results))

        def run(job):
            command, op_id = job
            with migrated_session(engine) as session:
                barrier.wait()
                try:
                    if command == "settle":
                        settle_delivered_operation(session, operation_id=op_id, delivered_attempt_number=1)
                    else:
                        expire_ai_operation(session, operation_id=op_id)
                    session.commit()
                    return command, op_id, True
                except (AIBillingStateError, sa.exc.DBAPIError) as error:
                    # A database refusal at the boundary is the lease guard agreeing with the service.
                    assert isinstance(error, AIBillingStateError) or "lease" in str(error)
                    session.rollback()
                    return command, op_id, False

        jobs = [(c, r.operation_id) for r in results for c in ("settle", "expire")]
        with ThreadPoolExecutor(len(jobs)) as pool:
            outcomes = list(pool.map(run, jobs))
        # A refusal at the exact boundary moved nothing; the runtime retries, and a response that
        # missed its live lease is then kept as delivered, unbilled (founder decision 2026-11-17).
        with migrated_session(engine) as session:
            for result in results:
                if not [1 for c, op_id, ok in outcomes if op_id == result.operation_id and ok and c == "settle"]:
                    settle_delivered_operation(session, operation_id=result.operation_id, delivered_attempt_number=1)
                    session.commit()
        with migrated_session(engine) as session:
            states = []
            for result in results:
                op = session.get(AIBillingOperation, result.operation_id)
                states.append(op.state)
                if op.state == "finalized":  # settled while its lease was live: charged exactly once
                    assert (op.delivery_status, charged(session, result.operation_id)) == ("delivered", 18)
                    assert not absorbed(session, result.operation_id)
                else:  # the lease lapsed first: delivered, released, never charged
                    assert (op.state, op.delivery_status, charged(session, result.operation_id)) == (
                        "expired", "delivered", 0)
                    assert [r.reason for r in absorbed(session, result.operation_id)] == ["reservation_expired"]
                assert session.get(CreditReservation, result.reservation_id).state in ("settled", "expired")
            settled, expired = states.count("finalized"), states.count("expired")
            assert settled >= 1 and expired >= 1, states  # both sides of the boundary ran
            assert sums(session, ns.account) == (500 - 18 * settled, 0)  # no hold is left behind
    finally:
        engine.dispose()


@PG
def test_postgres_f8_concurrent_operations_stop_at_each_members_own_limit():
    engine = _migrated_engine()
    try:
        ns = _pg_world(engine, credits=100_000, members=2, member={"max_operations": 2},
                       without_organization=True)
        owner, teammate = ns.members
        with migrated_session(engine) as session:
            ops = [(user, operation(session, ns, user)) for user in (owner, teammate) for _ in range(5)]
            session.commit()
        barrier = threading.Barrier(len(ops))

        def run(job):
            user, op_id = job
            with migrated_session(engine) as session:
                barrier.wait()
                outcome = authorize(session, ns, op_id, user).outcome
                session.commit()
                return user, outcome

        with ThreadPoolExecutor(len(ops)) as pool:
            outcomes = list(pool.map(run, ops))
        for user in (owner, teammate):  # each member's allowance is their own, from one shared balance
            assert sorted(o for u, o in outcomes if u == user) == ["authorized"] * 2 + ["capacity_denied"] * 3
        with migrated_session(engine) as session:
            assert sums(session, ns.account) == (100_000 - 4 * 36, 4 * 36)
    finally:
        engine.dispose()


@PG
def test_postgres_f8_concurrent_operations_respect_a_members_concurrency_limit():
    engine = _migrated_engine()
    try:
        ns = _pg_world(engine, credits=100_000, member={"max_concurrent": 2})
        with migrated_session(engine) as session:
            ops = [operation(session, ns) for _ in range(6)]
            session.commit()
        barrier = threading.Barrier(len(ops))

        def run(op_id):
            with migrated_session(engine) as session:
                barrier.wait()
                result = authorize(session, ns, op_id)
                session.commit()
                return result.outcome, result.reason_code

        with ThreadPoolExecutor(len(ops)) as pool:
            outcomes = list(pool.map(run, ops))
        assert sorted(outcomes, key=str) == sorted(
            [("authorized", None)] * 2 + [("capacity_denied", "member_concurrency")] * 4, key=str)
    finally:
        engine.dispose()
