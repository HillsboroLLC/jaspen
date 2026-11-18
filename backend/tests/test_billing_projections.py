"""Phase 13: pure billing projections and the legacy compatibility comparison.

Traceability D18 row 13 ("pure projections, all writer/reader inventory,
compatibility field proofs"), ADR-0001 derived target fields and projection
rule, lifecycle D23 (Usage & Billing), D16 (difference classes and special
cases), D17 T-READ-01..08 and the data assertions of T-USAGE-01..10.

Every test runs on the ORM schema: SQLite, or an isolated PostgreSQL schema
when TEST_DATABASE_URL is set. The records are built only through the
accepted Phase 6-12 commands (or, for legacy fields, the legacy columns
directly), so a projection is checked against what those phases actually
write. Every credit amount and policy number is a test fixture.
"""

from concurrent.futures import ThreadPoolExecutor
import contextlib
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import threading
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

import app.billing_config as billing_config
from app import db as flask_db
from app.billing_ai_operations import settle_delivered_operation
from app.billing_projections import (
    CLASSIFICATIONS,
    PROJECTION_VERSION,
    ProjectionError,
    ProjectionInvariantError,
    ProjectionIsolationError,
    compare_legacy_compatibility,
    project_billing_account,
    project_usage_history,
)
from app.billing_entitlements import add_calendar_months
from app.models import (
    AccountEntitlement,
    AIOperation,
    CreditLedgerEntry,
    CreditLot,
    IdempotencyRegistry,
    Organization,
    OrganizationMember,
    PersistentCreditGrant,
    PersistentCreditTransaction,
    User,
)
from app.models_billing_phase4 import BillingSubscription
from tests.test_billing_ai_operations import (
    _migrated_engine,
    account as funded_account,
    authorize,
    call,
    db_now,
    migrated_session,
    world,
)
from tests.test_billing_enterprise_contracts import (
    SEATS,
    active_contract,
    seed_org,
    self_serve,
    staff,
)
from tests.test_billing_enterprise_contracts import allocate as allocate_period
from tests.test_billing_financial_effects import PRICE, dispute, pack_purchase, seed_account


BACKEND = Path(__file__).resolve().parents[1]
PG = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="local disposable PostgreSQL is not configured")


def row_counts(session):
    return {
        table.name: session.execute(sa.select(sa.func.count()).select_from(table)).scalar_one()
        for table in sorted(flask_db.metadata.tables.values(), key=lambda t: t.name)
    }


def assert_pure(session, fn, **kwargs):
    """T-READ: two calls agree; no table changes; no pending change is created or flushed."""
    before = row_counts(session)
    pending = (set(session.new), set(session.dirty), set(session.deleted))
    first = fn(session, **kwargs)
    second = fn(session, **kwargs)
    assert first == second
    assert (set(session.new), set(session.dirty), set(session.deleted)) == pending
    assert row_counts(session) == before
    return first


def settled_operation(session, ns, user=None, *, tokens=(1000, 1000), thread_id=None):
    result = authorize(session, ns, user=user)
    if thread_id is not None:
        session.get(AIOperation, result.operation_id).thread_id = thread_id
        session.flush()
    call(session, result.operation_id, tokens=tokens)
    settle_delivered_operation(session, operation_id=result.operation_id, delivered_attempt_number=1)
    return result.operation_id


def ledger_sums(session, account_id):
    available, held = session.execute(sa.select(
        sa.func.coalesce(sa.func.sum(CreditLedgerEntry.available_delta), 0),
        sa.func.coalesce(sa.func.sum(CreditLedgerEntry.held_delta), 0),
    ).where(CreditLedgerEntry.billing_account_id == account_id)).one()
    return int(available), int(held)


# ---------------------------------------------------------------------------
# T-READ-01..08: every projection and the comparison are pure reads
# ---------------------------------------------------------------------------

def _empty(session):
    ns = seed_org(session)
    return ns, None


def _funded(session):
    ns = world(session)
    return ns, None


def _due(session):
    ns = funded_account(session)
    return ns, db_now(session) + timedelta(days=40)  # after the funded period ended


def _legacy(session):
    ns = world(session)
    user = session.get(User, ns.owner)
    user.credits_remaining, user.credits_reset_at = 777, datetime(2026, 1, 1)
    user.ui_preferences = {"thinking_power": {"remaining": 700, "cycle_reset_at": "2026-01-01T00:00:00"}}
    org = session.get(Organization, ns.org)
    org.settings = {"thinking_power": {"remaining": 700, "cycle_reset_at": "2026-01-01T00:00:00"}}
    session.flush()
    return ns, None


def _admin(session):
    ns = world(session)
    user = session.get(User, ns.owner)
    user.is_admin, user.subscription_plan = True, "enterprise"
    session.flush()
    return ns, None


def _organization(session):
    ns = world(session, members=3)
    settled_operation(session, ns, ns.members[1])
    return ns, None


def _in_flight(session):
    ns = world(session)
    authorize(session, ns)
    return ns, None


def _disputed(session):
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    dispute(session, ns, purchase.tx, f"dp_{ns.suffix}", {purchase.line: PRICE}, "opened")
    return ns, None


STATES = {"empty": _empty, "funded": _funded, "due": _due, "legacy": _legacy, "admin": _admin,
          "organization": _organization, "in_flight": _in_flight, "disputed": _disputed}


@pytest.mark.parametrize("state", sorted(STATES))
def test_t_read_projections_and_comparison_never_write_under_any_state(db, state):
    session = db.session
    ns, at = STATES[state](session)
    at = at or db_now(session)
    assert_pure(session, project_billing_account, billing_account_id=ns.account, at=at)
    assert_pure(session, project_usage_history, billing_account_id=ns.account)
    assert_pure(session, compare_legacy_compatibility, billing_account_id=ns.account, at=at)
    members = getattr(ns, "members", [])
    for member in members:
        assert_pure(session, project_billing_account, billing_account_id=ns.account, at=at, member_user_id=member)


def test_t_read_a_caller_pending_change_is_neither_flushed_nor_lost(db):
    session = db.session
    ns = world(session)
    before = row_counts(session)
    pending = User(id=f"pending-{uuid.uuid4().hex[:8]}", email=f"p-{uuid.uuid4().hex[:8]}@example.test",
                   name="pending", password_hash="x")
    session.add(pending)
    project_billing_account(session, billing_account_id=ns.account)
    compare_legacy_compatibility(session, billing_account_id=ns.account)
    assert pending in session.new
    assert row_counts(session) == before


def test_t_read_the_comparison_never_calls_the_writing_legacy_readers(db, monkeypatch):
    session = db.session
    ns = world(session)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("a legacy reader that writes on read was called")

    for name in ("get_usage_meter_state", "_resolve_user_pool", "_resolve_org_pool", "bootstrap_legacy_credits",
                 "reset_user_monthly_credits"):
        monkeypatch.setattr(billing_config, name, forbidden)
    compare_legacy_compatibility(session, billing_account_id=ns.account)


# ---------------------------------------------------------------------------
# Projection equals the ledger (T-USAGE data assertions)
# ---------------------------------------------------------------------------

def test_projection_equals_the_ledger_after_allocation_and_settlement(db):
    session = db.session
    ns = world(session)
    operation_id = settled_operation(session, ns, thread_id="session-a")
    view = project_billing_account(session, billing_account_id=ns.account)
    available, held = ledger_sums(session, ns.account)
    assert view["projection_version"] == PROJECTION_VERSION
    assert (view["credits"]["available"], view["credits"]["held"]) == (available, held) == (500 - 18, 0)
    assert view["credits"]["recurring_available"] == 482 and view["credits"]["purchased_available"] == 0
    assert view["credits"]["period_remaining"] == 482
    assert view["credits"]["used_this_period"] == 18  # settled usage, never limit minus a balance
    assert view["effective_plan_key"] == ns.tier and view["plan_source_type"] == "subscription"
    history = project_usage_history(session, billing_account_id=ns.account)
    assert history["total_charged_credits"] == 18
    [operation] = history["operations"]
    assert (operation["operation_id"], operation["session_id"], operation["charged_credits"]) == (
        operation_id, "session-a", 18)
    assert history["sessions"] == [{
        "session_id": "session-a", "charged_credits": 18, "operations": 1,
        "first_activity_at": operation["finalized_at"], "last_activity_at": operation["finalized_at"],
    }]


def test_an_open_reservation_is_held_not_available_and_never_shown_as_used(db):
    session = db.session
    ns = world(session)
    authorize(session, ns)
    credits = project_billing_account(session, billing_account_id=ns.account)["credits"]
    assert (credits["available"], credits["held"], credits["used_this_period"]) == (500 - 36, 36, 0)


def test_member_view_counts_only_that_members_usage_and_spendable_lots(db):
    session = db.session
    ns = world(session, members=2)
    owner, teammate = ns.members
    settled_operation(session, ns, owner, thread_id="s-owner")
    settled_operation(session, ns, teammate, tokens=(2000, 2000), thread_id="s-team")
    owner_view = project_billing_account(session, billing_account_id=ns.account, member_user_id=owner)
    team_view = project_billing_account(session, billing_account_id=ns.account, member_user_id=teammate)
    assert owner_view["credits"]["used_this_period"] == 18 and team_view["credits"]["used_this_period"] == 36
    assert owner_view["credits"]["member_spendable"] == team_view["credits"]["member_spendable"] == 500 - 54
    history = project_usage_history(session, billing_account_id=ns.account, member_user_id=teammate)
    assert [s["session_id"] for s in history["sessions"]] == ["s-team"]


def test_recurring_and_purchased_credits_are_separate_and_dates_follow_the_term(db):
    session = db.session
    ns = seed_org(session)
    anchor = db_now(session) - timedelta(hours=3)
    sub = self_serve(session, ns, "month", credits=500, anchor=anchor)
    allocate_period(session, ns, sub, 0, at=anchor + timedelta(hours=2))
    view = project_billing_account(session, billing_account_id=ns.account, display_time_zone="America/New_York")
    term_end = add_calendar_months(anchor, 1)
    assert view["credits"]["recurring_available"] == 500
    assert view["next_allocation_at"] == term_end.isoformat()
    assert view["subscription"]["next_payment_at"] == term_end.isoformat()
    assert view["subscription"]["billing_interval"] == "month" and view["subscription"]["status"] == "active"
    assert view["display"]["next_allocation_at"].endswith(("-05:00", "-04:00"))
    assert datetime.fromisoformat(view["display"]["next_allocation_at"]) == term_end
    # A subscription ending at period end funds no further period and takes no further payment.
    session.get(BillingSubscription, sub.subscription.id).state = "cancel_at_period_end"
    session.flush()
    ending = project_billing_account(session, billing_account_id=ns.account)
    assert ending["next_allocation_at"] is None and ending["subscription"]["next_payment_at"] is None


def _utc_anchor(subscription):
    anchor = subscription.anchor_at
    return anchor.replace(tzinfo=timezone.utc) if anchor.tzinfo is None else anchor


def test_a_paid_upgrade_mid_period_keeps_the_period_and_adds_its_prorated_lot(db, test_user):
    from app.billing_plan_changes import apply_paid_upgrade
    from tests.test_billing_plan_changes import DELIVERIES as P7_DELIVERIES, _line as p7_line, _target
    from tests.test_billing_plan_changes import _subscription_foundation
    from app.billing_allocations import allocate_recurring_credits
    account, _old, prior, subscription, old_line = _subscription_foundation(db, test_user, interval="month")
    allocate_recurring_credits(
        db.session, billing_account_id=account.id, entitlement_instance_id=prior.id, period_index=0,
        opened_at=_utc_anchor(subscription) + timedelta(hours=2), delivery_obligations=P7_DELIVERIES,
        financial_line_id=old_line.id, actor_type="system", actor_id="phase13-test",
    )
    paid_at = datetime(2026, 2, 10, 15, 45, tzinfo=timezone.utc)
    definition, target = _target(db, account, subscription, 900, starts_at=paid_at)
    apply_paid_upgrade(
        db.session, billing_account_id=account.id, subscription_id=subscription.id,
        prior_entitlement_instance_id=prior.id, target_entitlement_instance_id=target.id,
        financial_line_id=p7_line(db, account, subscription, target, paid_at).id, paid_at=paid_at,
        period_index=0, actor_type="system", actor_id="phase13-test", delivery_obligations=P7_DELIVERIES,
    )
    view = project_billing_account(db.session, billing_account_id=account.id, at=paid_at + timedelta(hours=1))
    available, _held = ledger_sums(db.session, account.id)
    assert view["effective_plan_key"] == definition.key
    assert view["credits"]["recurring_available"] == view["credits"]["period_remaining"] == available
    assert view["credits"]["period_remaining"] == 500 + 257  # the period allocation plus the prorated upgrade
    assert view["next_allocation_at"] == datetime(2026, 2, 28, 15, 45, tzinfo=timezone.utc).isoformat()


def test_a_pack_purchase_is_purchased_credit_and_a_dispute_hold_is_not_available(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    before = project_billing_account(session, billing_account_id=ns.account)["credits"]
    assert before["purchased_available"] > 0 and before["recurring_available"] == 0
    dispute(session, ns, purchase.tx, f"dp_{ns.suffix}", {purchase.line: PRICE}, "opened")
    after = project_billing_account(session, billing_account_id=ns.account)["credits"]
    available, held = ledger_sums(session, ns.account)
    assert (after["available"], after["held"]) == (available, held)
    assert after["held"] > 0 and after["available"] < before["available"]
    report = compare_legacy_compatibility(session, billing_account_id=ns.account)
    assert {"code": "active_dispute", "count": 1, "blocks_cutover": True,
            "detail": "migrate case state and source hold before exposing balance"} in report["flags"]
    assert report["blocked"]


def test_expired_recurring_value_is_never_available(db):
    session = db.session
    ns = funded_account(session)
    later = db_now(session) + timedelta(days=40)
    view = project_billing_account(session, billing_account_id=ns.account, at=later)
    assert view["credits"]["available"] == 0 and view["credits"]["period_remaining"] is None


def test_enterprise_contract_projection_reports_contract_seats_and_no_self_serve_payment(db):
    session = db.session
    ns = seed_org(session, members=3)
    _contract, version, _activation = active_contract(session, ns, staff(session))
    view = project_billing_account(session, billing_account_id=ns.account)
    assert view["plan_source_type"] == "enterprise_contract"
    assert view["contract_access"]["state"] == "paid"
    assert view["seats"] == {"commitment": SEATS, "occupancy": 3}
    assert view["subscription"]["subscription_id"] == version.subscription_id
    assert view["subscription"]["next_payment_at"] is None  # invoiced by contract, not projected
    assert view["access_restricted"] == {"restricted": False, "reason": None}


def test_capacity_is_reported_apart_from_credits(db):
    session = db.session
    ns = world(session, members=2, member={"max_operations": 1})
    owner, teammate = ns.members
    authorize(session, ns, user=owner)
    denied = authorize(session, ns, user=owner)
    assert denied.outcome == "capacity_denied"
    owner_view = project_billing_account(session, billing_account_id=ns.account, member_user_id=owner)
    assert owner_view["capacity"]["status"] == "temporarily_unavailable"
    assert owner_view["capacity"]["reason_code"] == "member_window"
    assert owner_view["capacity"]["available_again_at"] is not None
    assert owner_view["credits"]["member_spendable"] == 500 - 36  # capacity denial moves no credit
    team_view = project_billing_account(session, billing_account_id=ns.account, member_user_id=teammate)
    assert team_view["capacity"]["status"] == "no_decision_recorded"


def test_a_restricted_billing_account_is_reported_restricted(db):
    session = db.session
    ns = world(session)
    from app.models import BillingAccount
    session.get(BillingAccount, ns.account).status = "restricted"
    session.flush()
    view = project_billing_account(session, billing_account_id=ns.account)
    assert view["access_restricted"] == {"restricted": True, "reason": "billing_account_restricted"}


# ---------------------------------------------------------------------------
# Tenant isolation
# ---------------------------------------------------------------------------

def test_projections_are_isolated_between_organizations(db):
    session = db.session
    first, second = world(session), funded_account(session, credits=900)
    settled_operation(session, first, thread_id="first-session")
    first_view = project_billing_account(session, billing_account_id=first.account)
    second_view = project_billing_account(session, billing_account_id=second.account)
    assert first_view["credits"]["available"] == 482 and second_view["credits"]["available"] == 900
    assert project_usage_history(session, billing_account_id=second.account)["operations"] == []
    with pytest.raises(ProjectionIsolationError):
        project_billing_account(session, billing_account_id=first.account, member_user_id=second.owner)
    with pytest.raises(ProjectionIsolationError):
        project_usage_history(session, billing_account_id=first.account, member_user_id=second.owner)


def test_a_lot_attributed_to_one_member_is_not_spendable_by_another(db):
    session = db.session
    ns = world(session, members=2)
    owner, teammate = ns.members
    lot = session.get(CreditLot, ns.lot.id)
    lot.member_attribution_id = owner
    session.flush()
    owner_view = project_billing_account(session, billing_account_id=ns.account, member_user_id=owner)
    team_view = project_billing_account(session, billing_account_id=ns.account, member_user_id=teammate)
    assert owner_view["credits"]["member_spendable"] == 500
    assert team_view["credits"]["member_spendable"] == 0
    assert team_view["credits"]["attributed_to_other_members"] == 500


def test_a_scoped_lot_fails_closed(db):
    session = db.session
    ns = world(session)
    session.get(CreditLot, ns.lot.id).eligibility_scope = {"capability": "fixture"}
    session.flush()
    credits = project_billing_account(session, billing_account_id=ns.account, member_user_id=ns.owner)["credits"]
    assert credits["available"] == 0 and credits["member_spendable"] == 0 and credits["scoped_unspendable"] == 500


def test_an_unknown_account_or_display_zone_is_refused(db):
    session = db.session
    ns = world(session)
    with pytest.raises(ProjectionError, match="does not exist"):
        project_billing_account(session, billing_account_id="missing")
    with pytest.raises(ProjectionError, match="time zone"):
        project_billing_account(session, billing_account_id=ns.account, display_time_zone="Mars/Olympus")


# ---------------------------------------------------------------------------
# Invariant violations raise; nothing is clamped
# ---------------------------------------------------------------------------

def _raw_entry(session, ns, **values):
    registry = IdempotencyRegistry(
        id=str(uuid.uuid4()), namespace="phase13_corruption_fixture", key=str(uuid.uuid4()),
        request_fingerprint="d" * 64, state="claimed", claimed_at=datetime.now(timezone.utc),
    )
    session.add(registry)
    session.flush()
    session.add(CreditLedgerEntry(
        id=str(uuid.uuid4()), billing_account_id=ns.account, lot_id=ns.lot.id, idempotency_registry_id=registry.id,
        effective_at=datetime.now(timezone.utc), actor_type="test", actor_id="phase13", reason_code="corruption",
        evidence_json={}, **values,
    ))
    session.flush()


def test_a_ledger_below_the_zero_floor_is_rejected_not_clamped(db):
    session = db.session
    ns = funded_account(session)
    _raw_entry(session, ns, entry_type="admin_adjustment", available_delta=-600, held_delta=0)
    with pytest.raises(ProjectionInvariantError, match="zero floor"):
        project_billing_account(session, billing_account_id=ns.account)
    with pytest.raises(ProjectionInvariantError, match="zero floor"):
        compare_legacy_compatibility(session, billing_account_id=ns.account)


def test_two_active_base_plans_are_rejected(db):
    session = db.session
    ns = seed_org(session)
    anchor = db_now(session) - timedelta(hours=3)
    self_serve(session, ns, "month", anchor=anchor)
    self_serve(session, ns, "month", anchor=anchor)
    with pytest.raises(ProjectionInvariantError, match="more than one base plan"):
        project_billing_account(session, billing_account_id=ns.account)


def test_an_operation_whose_recorded_charge_disagrees_with_its_settlement_is_rejected(db):
    session = db.session
    ns = world(session)
    operation_id = settled_operation(session, ns)
    from app.models_billing_phase12 import AIBillingOperation
    session.get(AIBillingOperation, operation_id).charged_credits = 99
    session.flush()
    with pytest.raises(ProjectionInvariantError, match="settled 18"):
        project_usage_history(session, billing_account_id=ns.account)


# ---------------------------------------------------------------------------
# Legacy compatibility comparison (D16 classes and special cases)
# ---------------------------------------------------------------------------

def _owner_counter(report, owner):
    [item] = [c for c in report["comparisons"] if c["field"] == "users.credits_remaining" and c["subject"] == owner]
    return item


def _set_owner(session, ns, *, credits, reset_at=None, meter=None):
    user = session.get(User, ns.owner)
    user.credits_remaining = credits
    user.credits_reset_at = reset_at if reset_at is not None else datetime.now(timezone.utc) - timedelta(days=2)
    if meter is not None:
        user.ui_preferences = {"thinking_power": meter}
    session.flush()


def _grant(session, user_id, remaining, *, original=None, log_balance=None):
    grant = PersistentCreditGrant(
        user_id=user_id, source="credit_pack", original_amount=original or remaining, remaining_amount=remaining,
        status="active", external_reference=f"legacy-{uuid.uuid4().hex}",
    )
    session.add(grant)
    session.flush()
    if log_balance is not None:
        session.add(PersistentCreditTransaction(
            grant_id=grant.id, user_id=user_id, transaction_type="grant", amount=original or remaining,
            balance_after=log_balance,
        ))
        session.flush()
    return grant


@pytest.mark.parametrize("case,expected,special", [
    ("match", "match", None),
    ("negative", "unresolved", "negative_legacy_meter"),
    ("shared_pool", "known_projection_duplication", "shared_pool_copied"),
    ("stale", "known_stale_counter", "expired_recurring_value"),
    ("persistent", "evidence_backed_adjustment", None),
    ("above", "unresolved", "counter_above_evidence"),
    ("below_purchased", "unresolved", "counter_below_proven_purchased"),
])
def test_the_combined_counter_is_classified_with_the_d16_classes(db, case, expected, special):
    session = db.session
    if case == "below_purchased":
        ns = seed_account(session)
        session.add(OrganizationMember(organization_id=ns.org, user_id=ns.owner, role="owner", status="active"))
        session.flush()
        pack_purchase(session, ns)
        _set_owner(session, ns, credits=10)
    else:
        ns = world(session)
        if case == "match":
            _set_owner(session, ns, credits=500)
        elif case == "negative":
            _set_owner(session, ns, credits=-5)
        elif case == "shared_pool":
            session.get(Organization, ns.org).settings = {"thinking_power": {"remaining": 900}}
            session.get(User, ns.owner).subscription_plan = "team"  # a shared-pool plan meters the organization
            _set_owner(session, ns, credits=900)
        elif case == "stale":
            _set_owner(session, ns, credits=700, reset_at=datetime(2026, 1, 1),
                       meter={"remaining": 700, "cycle_limit": 1000, "cycle_reset_at": "2026-01-01T00:00:00"})
        elif case == "persistent":
            _grant(session, ns.owner, 250)
            _set_owner(session, ns, credits=750)
        elif case == "above":
            _set_owner(session, ns, credits=650)
    report = compare_legacy_compatibility(session, billing_account_id=ns.account)
    item = _owner_counter(report, ns.owner)
    assert (item["classification"], item["special_case"]) == (expected, special)
    assert set(report["summary"]) == set(CLASSIFICATIONS)
    assert report["blocked"] == (report["summary"]["unresolved"] > 0 or any(f["blocks_cutover"] for f in report["flags"]))


# H1 (acceptance review 2026-11-17): a stale classification needs positive, bounded evidence.

def _counter(session, ns, *, credits, reset_at=None, meter=None, at=None):
    user = session.get(User, ns.owner)
    user.credits_remaining, user.credits_reset_at = credits, reset_at
    user.ui_preferences = {"thinking_power": meter} if meter is not None else {}
    session.flush()
    report = compare_legacy_compatibility(session, billing_account_id=ns.account, at=at)
    return _owner_counter(report, ns.owner), report


def test_h1_reviewer_counterexample_is_unresolved_and_blocks(db):
    session = db.session
    ns = world(session)
    item, report = _counter(session, ns, credits=5_000_000)  # no reset date, no meter
    assert (item["classification"], item["special_case"]) == ("unresolved", "counter_above_evidence")
    assert report["blocked"] is True


@pytest.mark.parametrize("case", ["old_date_no_meter", "meter_without_limit", "above_cycle_limit",
                                  "unexplained_remainder", "missing_date_full_meter", "cycle_not_yet_ended"])
def test_h1_an_old_or_missing_reset_date_never_explains_a_difference(db, case):
    session = db.session
    ns = world(session)  # 500 recurring credits in the ledger
    old = "2026-01-01T00:00:00"
    now = db_now(session)
    at = None
    if case == "old_date_no_meter":
        kwargs = {"credits": 5_000_000, "reset_at": datetime(2025, 1, 1)}
    elif case == "meter_without_limit":
        kwargs = {"credits": 5_000_000, "meter": {"remaining": 5_000_000, "cycle_reset_at": old}}
    elif case == "above_cycle_limit":
        kwargs = {"credits": 5_000_000, "meter": {"remaining": 5_000_000, "cycle_limit": 1000, "cycle_reset_at": old}}
    elif case == "unexplained_remainder":  # the lapsed cycle explains 700 of an 800-credit difference
        kwargs = {"credits": 1300, "meter": {"remaining": 700, "cycle_limit": 1000, "cycle_reset_at": old}}
    elif case == "missing_date_full_meter":
        kwargs = {"credits": 700, "meter": {"remaining": 700, "cycle_limit": 1000}}
    else:  # one second before the cycle ends
        reset = now - timedelta(days=10)
        at = add_calendar_months(reset, 1) - timedelta(seconds=1)
        kwargs = {"credits": 700, "meter": {"remaining": 700, "cycle_limit": 1000,
                                            "cycle_reset_at": reset.isoformat()}, "at": at}
    item, report = _counter(session, ns, **kwargs)
    assert item["classification"] == "unresolved"
    assert report["blocked"] is True


def test_h1_a_lapsed_cycle_within_its_limit_is_stale_at_the_exact_boundary(db):
    session = db.session
    ns = world(session)
    now = db_now(session)
    reset = now - timedelta(days=10)
    boundary = add_calendar_months(reset, 1)
    meter = {"remaining": 1000, "cycle_limit": 1000, "cycle_reset_at": reset.isoformat()}
    item, _report = _counter(session, ns, credits=1000, meter=meter, at=boundary)
    assert (item["classification"], item["special_case"]) == ("known_stale_counter", "expired_recurring_value")


def test_h1_the_organization_meter_follows_the_same_rule(db):
    session = db.session
    ns = world(session)
    session.get(User, ns.owner).subscription_plan = "team"  # a shared-pool plan meters the organization
    org = session.get(Organization, ns.org)

    def org_item(meter):
        org.settings = {"thinking_power": meter}
        session.flush()
        report = compare_legacy_compatibility(session, billing_account_id=ns.account)
        [item] = [c for c in report["comparisons"]
                  if c["field"] == "organizations.settings.thinking_power.remaining"]
        return item, report

    item, report = org_item({"remaining": 5_000_000, "cycle_reset_at": "2025-01-01T00:00:00"})
    assert item["classification"] == "unresolved" and report["blocked"]
    item, report = org_item({"remaining": 5_000_000, "cycle_limit": 1000, "cycle_reset_at": "2025-01-01T00:00:00"})
    assert item["classification"] == "unresolved" and report["blocked"]
    item, _report = org_item({"remaining": 800, "cycle_limit": 1000, "cycle_reset_at": "2025-01-01T00:00:00"})
    assert (item["classification"], item["special_case"]) == ("known_stale_counter", "expired_recurring_value")
    item, _report = org_item({"remaining": 800, "cycle_limit": 1000})  # no reset date
    assert item["classification"] == "unresolved"


# M1: the meter and reset-date compatibility fields are compared, never silently used.

def _fields(report, subject):
    return {c["field"]: c for c in report["comparisons"] if c["subject"] == subject}


def test_m1_user_meter_and_reset_dates_are_reported_and_match_on_the_same_anchor(db):
    session = db.session
    ns = world(session)
    anchor = _utc_anchor(ns.sub.subscription)
    user = session.get(User, ns.owner)
    user.credits_remaining, user.credits_reset_at = 500, anchor
    user.ui_preferences = {"thinking_power": {"remaining": 500, "cycle_limit": 500, "cycle_reset_at": anchor.isoformat()}}
    session.flush()
    fields = _fields(compare_legacy_compatibility(session, billing_account_id=ns.account), ns.owner)
    for name in ("users.ui_preferences.thinking_power.remaining", "users.ui_preferences.thinking_power.cycle_reset_at",
                 "users.credits_reset_at"):
        assert fields[name]["classification"] == "match", name
    assert fields["users.ui_preferences.thinking_power.cycle_reset_at"]["projected"] == \
        add_calendar_months(anchor, 1).isoformat()


def test_m1_a_reset_date_from_another_anchor_is_unresolved_drift(db):
    session = db.session
    ns = world(session)
    drifted = _utc_anchor(ns.sub.subscription) + timedelta(days=5)
    user = session.get(User, ns.owner)
    user.credits_reset_at = drifted
    user.ui_preferences = {"thinking_power": {"remaining": 500, "cycle_reset_at": drifted.isoformat()}}
    session.flush()
    fields = _fields(compare_legacy_compatibility(session, billing_account_id=ns.account), ns.owner)
    for name in ("users.ui_preferences.thinking_power.cycle_reset_at", "users.credits_reset_at"):
        assert (fields[name]["classification"], fields[name]["special_case"]) == ("unresolved", "anchor_mismatch")


def test_m1_a_lapsed_reset_on_the_ledger_anchor_is_stale(db):
    session = db.session
    ns = seed_org(session)
    anchor = db_now(session) - timedelta(days=40)
    sub = self_serve(session, ns, "year", credits=500, anchor=anchor)
    allocate_period(session, ns, sub, 0, at=anchor + timedelta(hours=2))
    allocate_period(session, ns, sub, 1, at=add_calendar_months(anchor, 1) + timedelta(hours=2))
    session.get(User, ns.owner).credits_reset_at = anchor  # still the first period's reset
    session.flush()
    fields = _fields(compare_legacy_compatibility(session, billing_account_id=ns.account), ns.owner)
    item = fields["users.credits_reset_at"]
    assert (item["classification"], item["special_case"]) == ("known_stale_counter", "lapsed_reset_date")
    assert item["projected"] == add_calendar_months(anchor, 2).isoformat()


def test_m1_a_missing_or_malformed_meter_on_the_applicable_pool_is_visible_and_unresolved(db):
    session = db.session
    ns = world(session)
    report = compare_legacy_compatibility(session, billing_account_id=ns.account)
    fields = _fields(report, ns.owner)
    item = fields["users.ui_preferences.thinking_power.remaining"]
    assert (item["legacy"], item["classification"], item["special_case"]) == (None, "unresolved", "legacy_field_absent")
    # Personal plan: the organization meter is not the legacy pool; it is listed, not compared.
    assert {"subject": ns.org, "reason": "no member is on a shared-pool plan",
            "fields": "organizations.settings.thinking_power"} in report["not_applicable"]
    session.get(User, ns.owner).ui_preferences = {"thinking_power": {"remaining": "many", "cycle_reset_at": "soon"}}
    session.flush()
    fields = _fields(compare_legacy_compatibility(session, billing_account_id=ns.account), ns.owner)
    assert fields["users.ui_preferences.thinking_power.remaining"]["special_case"] == "malformed_legacy_meter"
    assert fields["users.ui_preferences.thinking_power.cycle_reset_at"]["special_case"] == "malformed_legacy_meter"


def test_m1_a_shared_pool_compares_the_organization_meter_and_lists_the_user_meter(db):
    session = db.session
    ns = world(session)
    session.get(User, ns.owner).subscription_plan = "team"
    session.flush()
    report = compare_legacy_compatibility(session, billing_account_id=ns.account)
    org_fields = _fields(report, ns.org)
    assert org_fields["organizations.settings.thinking_power.remaining"]["special_case"] == "legacy_field_absent"
    assert "organizations.settings.thinking_power.cycle_reset_at" in org_fields
    assert {"subject": ns.owner, "reason": "the user's plan meters the organization pool",
            "fields": "users.ui_preferences.thinking_power"} in report["not_applicable"]
    assert "users.credits_reset_at" in _fields(report, ns.owner)


# M2b (re-acceptance 2026-11-17): a pool the legacy runtime does not meter is listed, never compared.

def test_m2b_an_inapplicable_organization_meter_is_only_listed_as_not_applicable(db):
    session = db.session
    ns = world(session)  # personal plan: the legacy runtime meters the user, not the organization
    session.get(Organization, ns.org).settings = {"thinking_power": {
        "remaining": 123, "cycle_limit": 100, "cycle_reset_at": "2020-01-01T00:00:00"}}
    _set_owner(session, ns, credits=500)
    report = compare_legacy_compatibility(session, billing_account_id=ns.account)
    assert not [c for c in report["comparisons"] if c["field"].startswith("organizations.settings")]
    assert [n for n in report["not_applicable"] if n["subject"] == ns.org] == [
        {"subject": ns.org, "reason": "no member is on a shared-pool plan",
         "fields": "organizations.settings.thinking_power"}]


def test_m2b_an_inapplicable_user_meter_is_only_listed_as_not_applicable(db):
    session = db.session
    ns = world(session)
    user = session.get(User, ns.owner)
    user.subscription_plan = "team"
    user.ui_preferences = {"thinking_power": {"remaining": -4, "cycle_reset_at": "garbage"}}
    session.flush()
    report = compare_legacy_compatibility(session, billing_account_id=ns.account)
    fields = _fields(report, ns.owner)
    assert not [name for name in fields if name.startswith("users.ui_preferences")]
    assert "users.credits_reset_at" in fields  # the user's own reset date is still compared
    assert [n for n in report["not_applicable"] if n["subject"] == ns.owner] == [
        {"subject": ns.owner, "reason": "the user's plan meters the organization pool",
         "fields": "users.ui_preferences.thinking_power"}]


def test_m2b_a_dormant_organization_meter_is_not_evidence_for_a_personal_counter(db):
    session = db.session
    ns = world(session)
    session.get(Organization, ns.org).settings = {"thinking_power": {"remaining": 900}}
    _set_owner(session, ns, credits=900)  # personal plan; equals the dormant organization meter
    report = compare_legacy_compatibility(session, billing_account_id=ns.account)
    item = _owner_counter(report, ns.owner)
    assert (item["classification"], item["special_case"]) == ("unresolved", "counter_above_evidence")
    assert report["blocked"] is True


def test_m2b_the_applicable_meter_still_blocks_on_unresolved_evidence(db):
    session = db.session
    ns = world(session)
    session.get(User, ns.owner).subscription_plan = "team"
    session.get(Organization, ns.org).settings = {"thinking_power": {"remaining": -1}}
    session.flush()
    report = compare_legacy_compatibility(session, billing_account_id=ns.account)
    item = _fields(report, ns.org)["organizations.settings.thinking_power.remaining"]
    assert (item["classification"], item["special_case"]) == ("unresolved", "negative_legacy_meter")
    assert report["blocked"] is True
    assert not [n for n in report["not_applicable"] if n["subject"] == ns.org]


# L2: a null legacy balance is never a stale counter or a credit entitlement.

def test_l2_a_null_balance_on_a_sales_led_plan_without_a_contract_blocks(db):
    session = db.session
    ns = world(session)
    user = session.get(User, ns.owner)
    user.subscription_plan, user.credits_remaining = "enterprise_custom", None
    session.flush()
    report = compare_legacy_compatibility(session, billing_account_id=ns.account)
    item = _owner_counter(report, ns.owner)
    assert (item["classification"], item["special_case"]) == ("unresolved", "enterprise_without_contract")
    assert report["blocked"]


def test_l2_a_null_balance_on_a_sales_led_plan_is_explained_only_by_contract_funding(db):
    session = db.session
    ns = seed_org(session)
    active_contract(session, ns, staff(session))
    user = session.get(User, ns.owner)
    user.subscription_plan, user.credits_remaining = "enterprise_custom", None
    session.flush()
    item = _owner_counter(compare_legacy_compatibility(session, billing_account_id=ns.account), ns.owner)
    assert (item["classification"], item["special_case"]) == ("evidence_backed_adjustment", "unmetered_sales_led_plan")
    [contract_lot] = lots_of_account(session, ns.account)
    assert contract_lot.source_type == "subscription_recurring"  # Phase 11 contract-backed term lot
    # One credit that is not contract funding leaves the null balance unexplained.
    _grant_lot(session, ns.account, "promotional", 50)
    item = _owner_counter(compare_legacy_compatibility(session, billing_account_id=ns.account), ns.owner)
    assert (item["classification"], item["special_case"]) == ("unresolved", "unmetered_sales_led_plan")


def _grant_lot(session, account_id, source_type, amount):
    now = datetime.now(timezone.utc)
    lot = CreditLot(id=str(uuid.uuid4()), billing_account_id=account_id, source_type=source_type,
                    source_id=f"fixture-{uuid.uuid4().hex[:8]}", original_amount=amount,
                    available_at=now - timedelta(hours=1), expires_at=now + timedelta(days=30),
                    origin_evidence_json={"fixture": "phase13"})
    session.add(lot)
    session.flush()
    registry = IdempotencyRegistry(id=str(uuid.uuid4()), namespace="phase13_fixture_grant", key=lot.id,
                                   request_fingerprint="e" * 64, state="claimed", claimed_at=now)
    session.add(registry)
    session.flush()
    session.add(CreditLedgerEntry(
        id=str(uuid.uuid4()), billing_account_id=account_id, lot_id=lot.id, entry_type="grant",
        available_delta=amount, held_delta=0, idempotency_registry_id=registry.id, effective_at=now,
        actor_type="test", actor_id="phase13", reason_code="fixture_grant", evidence_json={},
    ))
    session.flush()
    return lot


def test_l2_a_null_balance_on_a_metered_plan_is_unresolved_not_stale(db):
    session = db.session
    ns = world(session)
    session.get(User, ns.owner).credits_remaining = None
    session.flush()
    item = _owner_counter(compare_legacy_compatibility(session, billing_account_id=ns.account), ns.owner)
    assert (item["classification"], item["special_case"]) == ("unresolved", "null_legacy_balance")


def lots_of_account(session, account_id):
    return session.execute(sa.select(CreditLot).where(CreditLot.billing_account_id == account_id)).scalars().all()


def test_an_in_flight_reservation_blocks_and_is_never_inferred_from_the_counter(db):
    session = db.session
    ns = world(session)
    authorize(session, ns)
    _set_owner(session, ns, credits=500)  # legacy still shows the pre-hold balance
    report = compare_legacy_compatibility(session, billing_account_id=ns.account)
    item = _owner_counter(report, ns.owner)
    assert (item["classification"], item["special_case"]) == ("unresolved", "in_flight_reservation")
    assert any(f["code"] == "in_flight_reservation" and f["blocks_cutover"] for f in report["flags"])
    assert report["blocked"]


def test_a_persistent_grant_whose_log_disagrees_is_unresolved(db):
    session = db.session
    ns = world(session)
    agreeing = _grant(session, ns.owner, 300, log_balance=300)
    disagreeing = _grant(session, ns.owner, 300, original=400, log_balance=250)
    report = compare_legacy_compatibility(session, billing_account_id=ns.account)
    by_grant = {c["subject"]: c for c in report["comparisons"]
                if c["field"] == "persistent_credit_grants.remaining_amount"}
    assert by_grant[agreeing.id]["classification"] == "match"
    assert (by_grant[disagreeing.id]["classification"], by_grant[disagreeing.id]["special_case"]) == (
        "unresolved", "persistent_grant_log_mismatch")


def test_an_enterprise_label_without_a_contract_is_unresolved_and_with_one_is_compared(db):
    session = db.session
    ns = world(session)
    session.get(Organization, ns.org).plan_key = "enterprise_custom"  # the legacy sales-led Enterprise label
    session.flush()
    report = compare_legacy_compatibility(session, billing_account_id=ns.account)
    [plan] = [c for c in report["comparisons"] if c["field"] == "organizations.plan_key"]
    assert (plan["classification"], plan["special_case"]) == ("unresolved", "enterprise_without_contract")
    contracted = seed_org(session)
    active_contract(session, contracted, staff(session))
    report = compare_legacy_compatibility(session, billing_account_id=contracted.account)
    [plan] = [c for c in report["comparisons"] if c["field"] == "organizations.plan_key"]
    assert plan["special_case"] is None


def test_plan_status_seats_offers_and_operation_charges_are_compared(db):
    session = db.session
    ns = world(session)
    operation_id = settled_operation(session, ns)
    user = session.get(User, ns.owner)
    user.subscription_plan, user.subscription_status = ns.tier, "active"
    org = session.get(Organization, ns.org)
    org.plan_key, org.max_total_paid_seats = ns.tier, None
    session.add(AccountEntitlement(user_id=ns.owner, entitlement_key="legacy_offer", source="test"))
    session.get(AIOperation, operation_id).charged_credits = 18
    session.flush()
    report = compare_legacy_compatibility(session, billing_account_id=ns.account)
    by_field = {c["field"]: c for c in report["comparisons"]}
    assert by_field["users.subscription_plan"]["classification"] == "match"
    assert by_field["users.subscription_status"]["classification"] == "match"
    assert by_field["organizations.plan_key"]["classification"] == "match"
    assert by_field["organizations.max_total_paid_seats"]["classification"] == "match"
    assert by_field["account_entitlements (has_offer)"]["classification"] == "unresolved"  # no target offer
    assert by_field["ai_operations.charged_credits"]["classification"] == "match"
    session.get(AIOperation, operation_id).charged_credits = 17
    session.flush()
    report = compare_legacy_compatibility(session, billing_account_id=ns.account)
    [charge] = [c for c in report["comparisons"] if c["field"] == "ai_operations.charged_credits"]
    assert charge["classification"] == "unresolved"


def test_the_comparison_is_deterministic(db):
    session = db.session
    ns = world(session, members=3)
    settled_operation(session, ns, ns.members[2])
    at = db_now(session)
    assert compare_legacy_compatibility(session, billing_account_id=ns.account, at=at) == \
        compare_legacy_compatibility(session, billing_account_id=ns.account, at=at)


# ---------------------------------------------------------------------------
# Inactive: no live caller
# ---------------------------------------------------------------------------

PHASE13_MODULE = "app/billing_projections.py"


def phase13_live_importers(backend):
    """Every app file other than the module that names it, by any import syntax (L1).

    A text match is deliberately broader than any import form: ``from . import
    billing_projections``, ``from app import billing_projections``, ``import
    app.billing_projections``, ``from .billing_projections import ...`` and
    ``importlib.import_module("app.billing_projections")`` all contain the name.
    """
    return sorted(
        str(path.relative_to(backend)) for path in (backend / "app").rglob("*.py")
        if str(path.relative_to(backend)) != PHASE13_MODULE and "billing_projections" in path.read_text()
    )


def test_phase13_projections_have_no_live_callers():
    assert phase13_live_importers(BACKEND) == []


@pytest.mark.parametrize("source", [
    "from . import billing_projections\n",
    "from app import billing_projections\n",
    "from app import billing_config, billing_projections as projections\n",
    "import app.billing_projections\n",
    "from .billing_projections import project_billing_account\n",
    "from app.billing_projections import compare_legacy_compatibility as compare\n",
    "import importlib\nprojections = importlib.import_module('app.billing_projections')\n",
])
def test_l1_no_import_syntax_bypasses_the_live_caller_guard(tmp_path, source):
    (tmp_path / "app" / "routes").mkdir(parents=True)
    (tmp_path / "app" / "billing_projections.py").write_text("PROJECTION_VERSION = 'x'\n")
    (tmp_path / "app" / "routes" / "usage.py").write_text(source)
    assert phase13_live_importers(tmp_path) == ["app/routes/usage.py"]


def test_l1_earlier_allowlists_exempt_only_the_one_inactive_phase13_module():
    """The five earlier guards exempt ``billing_projections.py`` by file name; only one such file may exist."""
    assert [str(p.relative_to(BACKEND)) for p in (BACKEND / "app").rglob("billing_projections.py")] == [PHASE13_MODULE]
    guards = {
        "test_billing_ai_operations.py": "test_phase12_service_has_no_live_runtime_callers",
        "test_billing_enterprise_contracts.py": "test_phase11_service_has_no_live_runtime_callers",
        "test_billing_seats.py": "test_seat_service_has_no_live_runtime_callers",
        "test_entitlement_period_foundation.py": "test_phase_4_policy_has_no_live_runtime_importers",
        "test_event_inbox.py": "test_inbox_has_no_live_runtime_importers",
    }
    for filename, guard in guards.items():
        source = (BACKEND / "tests" / filename).read_text()
        body = source[source.index(f"def {guard}("):]
        body = body[:body.index("\ndef ", 1)]
        assert body.count("billing_projections") == 1, filename  # one allowlist entry, nothing broader


# ---------------------------------------------------------------------------
# Fully migrated PostgreSQL 18.6 (every Phase 3-12 guard live)
# ---------------------------------------------------------------------------



@contextlib.contextmanager
def read_only_snapshot(engine):
    """One REPEATABLE READ, READ ONLY transaction: the database itself refuses any write."""
    with Session(engine.execution_options(isolation_level="REPEATABLE READ"), expire_on_commit=False) as session:
        session.execute(sa.text("SET TRANSACTION READ ONLY"))
        yield session
        session.commit()


def _project_everything(session, ns):
    account = project_billing_account(session, billing_account_id=ns.account)
    history = project_usage_history(session, billing_account_id=ns.account)
    report = compare_legacy_compatibility(session, billing_account_id=ns.account)
    members = [project_billing_account(session, billing_account_id=ns.account, member_user_id=m) for m in ns.members]
    return account, history, report, members


@PG
def test_postgres_migrated_projections_run_inside_a_read_only_transaction():
    engine = _migrated_engine()
    try:
        with migrated_session(engine) as session:
            ns = world(session, members=2)
            session.commit()
            settled_operation(session, ns, ns.members[1], thread_id="pg-session")
            session.commit()
            authorize(session, ns)  # one in-flight reservation
            user = session.get(User, ns.owner)
            user.credits_remaining, user.credits_reset_at = 900, datetime(2026, 1, 1)
            session.commit()
            available, held = ledger_sums(session, ns.account)
        with read_only_snapshot(engine) as session:
            account, history, report, members = _project_everything(session, ns)
        assert (account["credits"]["available"], account["credits"]["held"]) == (available, held) == (500 - 18 - 36, 36)
        assert history["total_charged_credits"] == 18 and history["sessions"][0]["session_id"] == "pg-session"
        assert report["blocked"] and any(f["code"] == "in_flight_reservation" for f in report["flags"])
        assert [m["credits"]["used_this_period"] for m in members] == [0, 18]
    finally:
        engine.dispose()


@PG
def test_postgres_migrated_snapshot_projection_conserves_credits_during_concurrent_settlements():
    """D16 conservation, observed live: available + held + settled = funded, in every snapshot."""
    engine = _migrated_engine()
    try:
        with migrated_session(engine) as session:
            ns = world(session, credits=500)
            session.commit()
            operations = []
            for _ in range(6):
                result = authorize(session, ns)
                call(session, result.operation_id)
                session.commit()
                operations.append(result.operation_id)
        done = threading.Event()
        observed = []

        def settle(operation_id):
            with migrated_session(engine) as session:
                settle_delivered_operation(session, operation_id=operation_id, delivered_attempt_number=1)
                session.commit()

        def observe():
            while not done.is_set() or len(observed) < 3:
                with read_only_snapshot(engine) as session:
                    credits = project_billing_account(session, billing_account_id=ns.account)["credits"]
                    charged = project_usage_history(session, billing_account_id=ns.account)["total_charged_credits"]
                observed.append(credits["available"] + credits["held"] + charged)

        with ThreadPoolExecutor(4) as pool:
            watcher = pool.submit(observe)
            list(pool.map(settle, operations))
            done.set()
            watcher.result()
        assert observed and set(observed) == {500}
        with read_only_snapshot(engine) as session:
            final = project_billing_account(session, billing_account_id=ns.account)["credits"]
        assert (final["available"], final["held"]) == (500 - 6 * 18, 0)
    finally:
        engine.dispose()
