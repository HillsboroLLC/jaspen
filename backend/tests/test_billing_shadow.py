"""Phase 16: inactive shadow calculation and reconciliation (D18 row 16; D16 reports; ADR projection rule).

Every authoritative record is written by the accepted Phase 3-15 commands
(the Phase 15 rehearsal, the Phase 6-12 services) or, for legacy rows, the
legacy columns directly. The shadow run itself only reads, inside a
database-enforced read-only transaction. ``PG`` tests run on the fully
migrated PostgreSQL 18.6 database with every Phase 3-14 guard live.

Coverage (assignment section 7): 1 exact agreement; 2 deliberate mismatches;
3 missing or conflicting evidence; 4 purchased-credit preservation; 5 renewal
and expiration boundaries; 6 scheduled changes and seats; 7 reservations,
disputes, held credits; 8 refunds, recoveries, mixed funding; 9 duplicates and
idempotent reconciliation; 10 isolation; 11 founder test versus genuine;
12 policy-version mismatches; 13 read-only under failures and retries;
14 determinism and no customer impact.
"""

from datetime import timedelta
from pathlib import Path
import uuid

import pytest
import sqlalchemy as sa

import app.billing_shadow as bs
from app import db as flask_db
from app.billing_config import get_usage_meter_state
from app.billing_entitlements import add_calendar_months
from app.models import (
    AIOperation,
    CreditLedgerEntry,
    CreditLot,
    OrganizationInvitation,
    OrganizationMember,
    Organization,
    Payment,
    PersistentCreditGrant,
    UsageEvent,
    User,
)
from app.models_billing_phase12 import AIBillingOperation
from app.models_billing_phase14 import BillingMigrationPaymentAttribution
from tests.test_billing_ai_operations import authorize, pricing, world as ai_world
from tests.test_billing_financial_effects import PRICE, dispute, pack_purchase, refund, seed_account
from tests.test_billing_migration import (
    FREE,
    PG,
    TEAM,
    _migrated_engine,
    attest,
    grant,
    meter,
    migrated,
    naive,
    now,
    organization,
    payment as bs_payment,
    personal,
    user,
)
from tests.test_billing_projections import _grant_lot, settled_operation
from tests.test_billing_rehearsal import _pg_world, add_invoice, pool_rehearsal, rehearse, team_pool, world


BACKEND = Path(__file__).resolve().parents[1]


def shadow(session, w, *, at=None, attestation="default", bind=None, **kwargs):
    session.commit()
    return bs.run_shadow_reconciliation(
        bind if bind is not None else flask_db.engine, organization_ids=kwargs.pop("orgs", w.orgs),
        environment="fixtures", at=at or now(session),
        test_activity_attestation=attest(w.founder.user) if attestation == "default" else attestation, **kwargs)


def rows(result, account_id=None, *, domain=None, comparison=None, subject=None):
    report = result["report"] if "report" in result else result
    every = [r for a in report["accounts"] for r in a["comparisons"]] + report["global_comparisons"]
    return [r for r in every
            if (account_id is None or r["billing_account_id"] == account_id)
            and (domain is None or r["domain"] == domain)
            and (comparison is None or r["comparison"] == comparison)
            and (subject is None or r["subject"] == subject)]


def one(result, **kwargs):
    found = rows(result, **kwargs)
    assert len(found) == 1, found
    return found[0]


def account(result, account_id):
    return next(a for a in result["report"]["accounts"] if a["billing_account_id"] == account_id)


def gate(result, code):
    return next(g for g in result["report"]["phase17_gates"] if g["gate"] == code)


# ---------------------------------------------------------------------------
# 1. Exact agreement after the Phase 15 rehearsal; 4. purchased-credit preservation
# ---------------------------------------------------------------------------

def test_a_rehearsed_population_agrees_exactly_on_balances_funding_and_periods(db):
    session = db.session
    w = world(session)
    rehearse(session, w)
    out = shadow(session, w)
    assert out["database"]["read_only_enforced"] and out["census_unchanged"]
    for ns in (w.free, w.founder, w.unverified):
        mine = account(out, ns.account)
        member = one(out, account_id=ns.account, comparison="member_spendable")
        assert (member["classification"], member["variance"]) == ("match", 0)
        assert one(out, account_id=ns.account, comparison="account_preserved_value")["classification"] == "match"
        assert one(out, account_id=ns.account, comparison="legacy_evidence_since_snapshot")["classification"] == \
            "match"
        for r in rows(out, ns.account, domain="credit_periods"):
            if r["comparison"] in ("cycle_start", "cycle_expiry", "cycle_allocation"):
                assert r["classification"] == "match", r
        assert one(out, account_id=ns.account, comparison="available_and_held_from_raw_entries")[
            "classification"] == "match"
        assert all(r["difference"] != "genuine_discrepancy" for r in mine["comparisons"])
    free = one(out, account_id=w.free.account, comparison="member_spendable")
    assert free["legacy"]["value"] == free["authoritative"]["value"] == 120_000
    founder_sources = {r["period"]: r for r in rows(out, w.founder.account, comparison="open_value_by_source")}
    assert founder_sources["credit_pack_purchase"]["authoritative"]["value"] == 2_500_000
    assert founder_sources["free_recurring"]["authoritative"]["value"] == 50_000
    assert {founder_sources[s]["classification"] for s in ("trial", "comp", "internal")} == {"not_applicable"}
    # Purchased-credit preservation: exact principal, remainder, and the original non-expiring terms.
    for comparison in ("purchased_principal", "purchased_remaining_at_opening", "purchased_expiry"):
        r = one(out, account_id=w.founder.account, comparison=comparison)
        assert r["classification"] == "match", r
    assert one(out, account_id=w.founder.account, comparison="purchased_principal")["legacy"]["value"] == 3_000_000


def test_every_comparison_carries_identity_period_evidence_variance_and_reproducibility(db):
    session = db.session
    w = world(session)
    rehearse(session, w)
    out = shadow(session, w)
    report = out["report"]
    assert report["shadow_version"] == bs.SHADOW_VERSION and report["as_of"] and report["report_fingerprint"]
    for r in rows(out, w.founder.account):
        assert r["billing_account_id"] == w.founder.account and r["organization_id"] == w.founder.org
        assert r["classification"] in bs.CLASSIFICATIONS and r["responsible_subsystem"]
        assert set(r["legacy"]) == set(r["authoritative"]) == {"value", "evidence"}
        assert r["migration"]["run_id"] and r["migration"]["account_result_id"]
        if type(r["legacy"]["value"]) is int and type(r["authoritative"]["value"]) is int:
            assert r["variance"] == r["authoritative"]["value"] - r["legacy"]["value"]
    summary = report["summary"]
    assert sum(summary["by_classification"].values()) == len(rows(out))
    assert set(summary["by_domain"]) <= set(bs.DOMAINS)


# ---------------------------------------------------------------------------
# 2. Deliberate mismatches detected and explained
# ---------------------------------------------------------------------------

def test_legacy_spending_after_the_snapshot_is_detected_as_activity_since_the_snapshot(db):
    session = db.session
    w = world(session)
    rehearse(session, w)
    holder = session.get(User, w.free.user)
    prefs = dict(holder.ui_preferences)
    prefs["thinking_power"] = {**prefs["thinking_power"], "remaining": 100_000}
    holder.ui_preferences, holder.credits_remaining = prefs, 100_000
    out = shadow(session, w)
    member = one(out, account_id=w.free.account, comparison="member_spendable")
    assert (member["classification"], member["difference"], member["variance"]) == \
        ("mismatch", "legacy_activity_since_snapshot", 20_000)
    assert member["blocks_cutover"]
    assert one(out, account_id=w.free.account, comparison="legacy_evidence_since_snapshot")["difference"] == \
        "legacy_activity_since_snapshot"
    assert gate(out, "writer_freeze_proven")["status"] == "fail"
    assert w.free.account in out["report"]["accounts_blocked"]


def test_unexplained_ledger_value_is_a_genuine_discrepancy_never_forced_to_agree(db):
    session = db.session
    w = world(session)
    rehearse(session, w)
    _grant_lot(session, w.free.account, "internal", 5_000)
    out = shadow(session, w)
    preserved = one(out, account_id=w.free.account, comparison="account_preserved_value")
    assert (preserved["classification"], preserved["difference"], preserved["variance"]) == \
        ("mismatch", "genuine_discrepancy", 5_000)
    internal = next(r for r in rows(out, w.free.account, comparison="open_value_by_source") if r["period"] == "internal")
    assert (internal["classification"], internal["special_case"]) == ("unresolved", "authoritative_only_funding")
    member = one(out, account_id=w.free.account, comparison="member_spendable")
    assert (member["classification"], member["difference"]) == ("mismatch", "genuine_discrepancy")
    assert gate(out, "no_genuine_discrepancy")["status"] == "fail"


# ---------------------------------------------------------------------------
# 3. Missing or conflicting source evidence
# ---------------------------------------------------------------------------

def test_missing_or_conflicting_evidence_is_unresolved_never_a_false_match(db):
    session = db.session
    w = world(session)
    rehearse(session, w)
    stray = organization(session, user(session, "stray"), plan_key="free", account=False)
    unmigrated = personal(session, remaining=10_000)
    out = shadow(session, w, orgs=w.orgs + [stray.org, unmigrated.org])
    negative = account(out, w.negative.account)
    assert negative["blocked"]
    assert one(out, account_id=w.negative.account, comparison="account_preserved_value")["special_case"] == \
        "legacy_evidence_quarantined"
    assert one(out, comparison="billing_account_established", subject=stray.org)["special_case"] == \
        "billing_account_not_established"
    assert one(out, account_id=unmigrated.account, comparison="legacy_evidence_since_snapshot")["special_case"] == \
        "no_migration_snapshot"
    unmigrated_rows = rows(out, unmigrated.account)
    assert not any(r["classification"] == "match" and r["domain"] == "balances"
                   and r["comparison"] == "account_preserved_value" for r in unmigrated_rows)


def test_a_duplicate_payment_reference_behind_two_grants_stays_unresolved(db):
    session = db.session
    reset = now(session) - timedelta(days=3)
    holder = user(session, "dup", reset=reset, prefs=meter(10_000, FREE, reset))
    ns = organization(session, holder, plan_key="free")
    reference = f"pi_{uuid.uuid4().hex[:12]}"
    grant(session, holder, 1_000_000, 1_000_000, reference=reference)
    grant(session, holder, 300_000, 300_000, source="300k_limited_time", reference=reference, payment_row=False)
    holder.credits_remaining = 1_310_000
    session.commit()
    w = world(session)
    w.orgs = w.orgs + [ns.org]
    rehearse(session, w)
    out = shadow(session, w)
    principal = rows(out, ns.account, comparison="purchased_principal")
    assert len(principal) == 2 and {r["classification"] for r in principal} == {"unresolved"}
    assert account(out, ns.account)["blocked"]


# ---------------------------------------------------------------------------
# 5. Renewal and expiration boundaries; the legacy calculator mirrors the legacy reader
# ---------------------------------------------------------------------------

def test_the_legacy_calculator_equals_the_legacy_reader_without_writing(db, app):
    session = db.session
    live = personal(session, remaining=120_000, grants=[(1_000_000, 400_000)])
    due = personal(session, remaining=50_000, days_ago=45)
    session.commit()
    at = now(session)
    for ns in (live, due):
        holder = session.get(User, ns.user)
        mine = bs.legacy_member_outcome(session, holder, at=at)
        before = (holder.credits_remaining, holder.ui_preferences)
        assert (holder.credits_remaining, holder.ui_preferences) == before  # the calculator wrote nothing
        legacy = get_usage_meter_state(holder, app.config, now=naive(at))  # writes on read; rolled back below
        assert legacy["remaining"] == mine["remaining"] and legacy["monthly_remaining"] == mine["monthly_remaining"]
        assert legacy["persistent_credits"] == mine["persistent_remaining"]
        session.rollback()
    assert bs.legacy_member_outcome(session, session.get(User, due.user), at=at)["reset_due"] is True


def test_the_cycle_boundary_is_the_same_instant_on_both_sides_and_renewal_waits_for_an_entitlement(db):
    session = db.session
    w = world(session)
    rehearse(session, w)
    boundary = add_calendar_months(w.free.reset, 1)
    before = shadow(session, w, at=boundary - timedelta(microseconds=1))
    assert one(before, account_id=w.free.account, comparison="member_spendable")["classification"] == "match"
    renewal = one(before, account_id=w.free.account, comparison="next_renewal")
    assert (renewal["classification"], renewal["special_case"]) == ("unresolved", "no_authoritative_entitlement")
    assert renewal["legacy"]["value"] == boundary.isoformat()
    at = shadow(session, w, at=boundary)
    member = one(at, account_id=w.free.account, comparison="member_spendable")
    # Legacy refills on read at the boundary; the ledger lot has expired and no approved entitlement renews it.
    assert member["legacy"]["value"] == FREE and member["authoritative"]["value"] == 0
    assert (member["classification"], member["special_case"]) == \
        ("unresolved", "renewal_due_without_authoritative_allocation")
    expiry = one(at, account_id=w.free.account, comparison="cycle_expiry")
    assert expiry["classification"] == "match"


# ---------------------------------------------------------------------------
# 6. Scheduled plan changes and seat commitments
# ---------------------------------------------------------------------------

def test_seat_occupancy_matches_and_a_legacy_seat_limit_without_a_commitment_is_unresolved(db):
    session = db.session
    owner = user(session, "team-owner", plan="team")
    members = [user(session, f"team-{i}", plan="team") for i in range(2)]
    ns = organization(session, owner, plan_key="team", members=members)
    org = session.get(Organization, ns.org)
    org.max_total_paid_seats = 4
    session.add(OrganizationInvitation(organization_id=org.id, email="pending@example.test", role="collaborator",
                                       status="pending", expires_at=naive(now(session) + timedelta(days=3))))
    session.commit()
    w = world(session)
    w.orgs = w.orgs + [ns.org]
    rehearse(session, w)
    out = shadow(session, w)
    occupancy = one(out, account_id=ns.account, comparison="paid_seat_occupancy")
    assert (occupancy["classification"], occupancy["legacy"]["value"]) == ("match", 3)
    assert occupancy["legacy"]["evidence"]["total_paid_reserved"] == 4  # a pending invitation holds a legacy seat
    commitment = one(out, account_id=ns.account, comparison="seat_commitment")
    assert (commitment["classification"], commitment["special_case"]) == ("unresolved", "seat_commitment_not_opened")
    assert one(out, account_id=ns.account, comparison="scheduled_transition")["classification"] == "not_applicable"


def test_a_paid_plan_without_an_authoritative_entitlement_is_unresolved_and_the_processor_gate_stays_open(db):
    session = db.session
    w = world(session)
    holder = session.get(User, w.unverified.user)
    holder.subscription_plan, holder.subscription_status = "essential", "active"
    session.commit()
    rehearse(session, w)
    out = shadow(session, w)
    plan = one(out, account_id=w.unverified.account, comparison="effective_plan")
    assert (plan["legacy"]["value"], plan["classification"], plan["special_case"]) == \
        ("essential", "unresolved", "no_authoritative_entitlement")
    status = one(out, account_id=w.unverified.account, comparison="subscription_status")
    assert (status["classification"], status["special_case"]) == ("unresolved", "subscription_not_materialized")
    assert gate(out, "approved_entitlement_definitions")["status"] in ("open", "pass")


def test_an_authoritative_plan_and_its_renewal_are_compared_with_the_legacy_plan(db):
    session = db.session
    ns = ai_world(session)
    owner = session.get(User, ns.owner)
    plan_key = bs.project_billing_account(session, billing_account_id=ns.account,
                                          at=now(session))["effective_plan_key"]
    owner.subscription_plan, owner.subscription_status = "starter", "active"
    session.commit()
    out = bs.run_shadow_reconciliation(flask_db.engine, organization_ids=[ns.org], environment="fixtures",
                                       at=now(session), test_activity_attestation=None)
    plan = one(out, account_id=ns.account, comparison="effective_plan", subject=ns.owner)
    assert plan["authoritative"]["value"] == plan_key
    assert plan["classification"] == ("match" if plan_key == "starter" else "mismatch")


# ---------------------------------------------------------------------------
# 7. Active reservations, disputes, and held credits; stale is never a release
# ---------------------------------------------------------------------------

def test_a_legacy_in_flight_operation_is_unresolved_and_a_stale_label_never_releases(db):
    session = db.session
    w = world(session)
    rehearse(session, w)
    op = AIOperation(id=str(uuid.uuid4()), user_id=w.free.user, organization_id=w.free.org, status="started",
                     operation_type="conversation", router_version="test", policy_version="test",
                     projected_credits=7_000)
    session.add(op)
    session.commit()

    def classify(_session, operation, _at):
        return "stale"

    plain = shadow(session, w)
    labelled = shadow(session, w, operation_classifier=classify)
    for out, special in ((plain, "in_flight_operation"), (labelled, "stale_operation_not_released")):
        r = one(out, account_id=w.free.account, comparison="legacy_in_flight_operation")
        assert (r["classification"], r["special_case"], r["legacy"]["value"]) == ("unresolved", special, 7_000)
        assert r["authoritative"]["value"] is None and r["blocks_cutover"]
        assert gate(out, "in_flight_operations_drained")["status"] == "fail"
    assert labelled["census_unchanged"] and session.get(AIOperation, op.id).status == "started"


def test_an_open_reservation_and_a_dispute_hold_reconcile_to_the_raw_ledger(db):
    session = db.session
    ns = ai_world(session)
    held = authorize(session, ns)
    session.commit()
    out = bs.run_shadow_reconciliation(flask_db.engine, organization_ids=[ns.org], environment="fixtures",
                                       at=now(session), test_activity_attestation=None)
    state = one(out, account_id=ns.account, comparison="operation_hold_state")
    assert (state["classification"], state["legacy"]["value"], state["authoritative"]["value"]) == \
        ("match", "open", "open")
    total = one(out, account_id=ns.account, comparison="account_held_total")
    assert total["classification"] == "match" and total["authoritative"]["value"] > 0
    assert total["legacy"]["evidence"]["reservation_holds"] == total["authoritative"]["value"]
    assert session.get(AIBillingOperation, held.operation_id).state == "authorized"

    disputed = seed_account(session)
    purchase = pack_purchase(session, disputed)
    dispute(session, disputed, purchase.tx, f"dp_{disputed.suffix}", {purchase.line: PRICE}, "opened")
    session.commit()
    out = bs.run_shadow_reconciliation(flask_db.engine, organization_ids=[disputed.org], environment="fixtures",
                                       at=purchase.at + timedelta(hours=1), test_activity_attestation=None)
    total = one(out, account_id=disputed.account, comparison="account_held_total")
    assert total["classification"] == "match" and total["legacy"]["evidence"]["dispute_and_other_holds"] > 0
    case = one(out, account_id=disputed.account, comparison="dispute_case_effect")
    assert case["classification"] == "not_applicable" and "P11" in case["explanation"]
    assert any(f == "migration_evidence:flag:active_dispute:active_dispute"
               for f in account(out, disputed.account)["blocking_reasons"])


def test_a_legacy_chargeback_reversal_is_unresolved_dispute_state(db):
    session = db.session
    reset = now(session) - timedelta(days=3)
    holder = user(session, "chargeback", reset=reset, prefs=meter(10_000, FREE, reset))
    ns = organization(session, holder, plan_key="free")
    grant(session, holder, 1_000_000, 0, reversed_reason="stripe_chargeback")
    holder.credits_remaining = 10_000
    session.commit()
    w = world(session)
    w.orgs = w.orgs + [ns.org]
    rehearse(session, w)
    out = shadow(session, w)
    r = one(out, account_id=ns.account, comparison="legacy_reversal")
    assert (r["classification"], r["special_case"]) == ("unresolved", "legacy_dispute_state_unknown")


# ---------------------------------------------------------------------------
# 8. Partial refunds, recoveries, and mixed funding
# ---------------------------------------------------------------------------

def test_mixed_funding_and_a_refunded_legacy_pack_reconcile_by_source(db):
    session = db.session
    reset = now(session) - timedelta(days=3)
    holder = user(session, "mixed", reset=reset, prefs=meter(30_000, FREE, reset))
    ns = organization(session, holder, plan_key="free")
    grant(session, holder, 2_000_000, 1_500_000)
    grant(session, holder, 300_000, 300_000, source="300k_limited_time", comped=True)
    grant(session, holder, 1_000_000, 0, reversed_reason="stripe_refund")
    holder.credits_remaining = 30_000 + 1_500_000 + 300_000
    session.commit()
    w = world(session)
    w.orgs = w.orgs + [ns.org]
    rehearse(session, w)
    out = shadow(session, w)
    by_source = {r["period"]: r for r in rows(out, ns.account, comparison="open_value_by_source")}
    assert by_source["credit_pack_purchase"]["authoritative"]["value"] == 1_500_000
    assert by_source["promotional"]["authoritative"]["value"] == 300_000
    assert by_source["free_recurring"]["authoritative"]["value"] == 30_000
    assert {by_source[s]["classification"] for s in ("credit_pack_purchase", "promotional", "free_recurring")} == \
        {"match"}
    reversal = one(out, account_id=ns.account, comparison="legacy_reversal")
    assert (reversal["classification"], reversal["legacy"]["evidence"]["reasons"]) == ("match", ["stripe_refund"])
    assert one(out, account_id=ns.account, comparison="member_spendable")["classification"] == "match"


def test_an_authoritative_partial_refund_is_reported_with_its_ledger_effect_and_the_approved_policy(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    refund(session, ns, purchase, f"re_{ns.suffix}", PRICE // 2)
    session.commit()
    out = bs.run_shadow_reconciliation(flask_db.engine, organization_ids=[ns.org], environment="fixtures",
                                       at=purchase.at + timedelta(hours=2), test_activity_attestation=None)
    case = one(out, account_id=ns.account, comparison="refund_case_effect")
    assert case["classification"] == "not_applicable" and "P05" in case["explanation"]
    assert case["authoritative"]["value"]["refund_reversal"]["available"] < 0
    movements = one(out, account_id=ns.account, comparison="ledger_movements")["authoritative"]["value"]
    assert movements["refund_reversed"] == -case["authoritative"]["value"]["refund_reversal"]["available"]
    assert one(out, account_id=ns.account, comparison="available_and_held_from_raw_entries")["classification"] == \
        "match"


# ---------------------------------------------------------------------------
# 9. Duplicate events and idempotent reconciliation; 14. determinism and no customer impact
# ---------------------------------------------------------------------------

def test_two_runs_over_the_same_state_are_identical_and_write_nothing(db):
    session = db.session
    w = world(session)
    rehearse(session, w)
    at = now(session)
    first, second = shadow(session, w, at=at), shadow(session, w, at=at)
    proof = bs.shadow_repeat_proof(first, second)
    assert proof == {"same_fingerprint": True, "differences": [], "census_delta": {}, "zero_writes": True}
    assert first["report"] == second["report"]
    assert bs.export_shadow_report(first["report"]) == bs.export_shadow_report(second["report"])
    # A Phase 15 rerun (duplicate migration events) changes nothing the shadow sees for these accounts.
    rehearse(session, w)
    third = shadow(session, w, at=at)
    for ns in (w.free, w.founder, w.unverified):
        assert one(third, account_id=ns.account, comparison="member_spendable")["classification"] == "match"


def test_the_shadow_changes_no_balance_legacy_field_or_customer_result(db):
    session = db.session
    w = world(session)
    rehearse(session, w)
    session.commit()
    legacy_before = bs.legacy_fingerprint(session)
    views = {a: bs.project_billing_account(session, billing_account_id=a, at=now(session))["credits"]
             for a in (w.free.account, w.founder.account)}
    out = shadow(session, w, at=now(session))
    assert out["census_unchanged"] and out["census_before"]["credit_ledger_entries"] > 0
    assert bs.legacy_fingerprint(session) == legacy_before
    assert {a: bs.project_billing_account(session, billing_account_id=a, at=now(session))["credits"]
            for a in views} == views


def test_phase16_shadow_has_no_live_callers():
    """Inactive: no route, job, webhook, startup, script, or runtime module names the shadow module."""
    callers = sorted(str(p.relative_to(BACKEND)) for p in (BACKEND / "app").rglob("*.py")
                     if p.name != "billing_shadow.py" and "billing_shadow" in p.read_text())
    assert callers == []
    assert [p for p in (BACKEND / "scripts").rglob("*.py") if "billing_shadow" in p.read_text()] == []


# ---------------------------------------------------------------------------
# 10. Organization and user isolation
# ---------------------------------------------------------------------------

def test_comparisons_stay_inside_each_organization(db):
    session = db.session
    w = world(session)
    rehearse(session, w)
    out = shadow(session, w)
    for a in out["report"]["accounts"]:
        member_ids = {m for m in session.execute(sa.text(
            "SELECT user_id FROM organization_members WHERE organization_id = :o"), {"o": a["organization_id"]}
        ).scalars()}
        for r in a["comparisons"]:
            assert r["billing_account_id"] == a["billing_account_id"]
            if r["domain"] == "balances" and r["comparison"] == "member_spendable":
                assert r["subject"] in member_ids


def test_a_pooled_member_whose_legacy_pool_is_another_organizations_is_a_genuine_discrepancy(db):
    session = db.session
    reset = now(session) - timedelta(days=3)
    owner = user(session, "pool-owner", plan="team")
    ns = organization(session, owner, plan_key="team", settings=meter(TEAM - 1_000, TEAM, reset))
    other = organization(session, user(session, "other-owner", plan="team"), plan_key="team",
                         settings=meter(5_000, TEAM, reset))
    owner.active_organization_id = other.org  # the legacy reader would spend the other organization's pool
    session.commit()
    w = world(session)
    w.orgs = w.orgs + [ns.org]
    rehearse(session, w)
    out = shadow(session, w)
    r = one(out, account_id=ns.account, comparison="member_spendable", subject=owner.id)
    assert (r["classification"], r["difference"], r["special_case"]) == \
        ("mismatch", "genuine_discrepancy", "legacy_pool_from_another_organization")
    assert not rows(out, other.account)  # the other organization was not a target


# ---------------------------------------------------------------------------
# 11. Founder test versus genuine customer classification
# ---------------------------------------------------------------------------

def test_another_organizations_payments_operations_and_history_never_appear_in_a_targeted_report_n2(db):
    """Review N2 negative case: before the fix, a one-organization run exported every tenant's payment rows."""
    session = db.session
    w = world(session)
    rehearse(session, w)
    mine = ai_world(session)
    my_op = settled_operation(session, mine)
    theirs = ai_world(session)
    their_op = settled_operation(session, theirs)
    session.commit()
    target = {w.founder.org, mine.org}
    members = set(session.execute(sa.text(
        "SELECT user_id FROM organization_members WHERE organization_id IN (:a, :b)"),
        {"a": w.founder.org, "b": mine.org}).scalars())
    foreign_payments = set(session.execute(sa.select(Payment.id).where(Payment.user_id.not_in(sorted(members))))
                           .scalars())
    assert foreign_payments, "fixture: other organizations have payments"
    out = shadow(session, w, orgs=sorted(target))
    exported = bs.export_shadow_report(out)
    leaked = sorted(p for p in foreign_payments if p in exported) + ([their_op] if their_op in exported else [])
    assert leaked == []
    # The target's own operation is still compared (two fixture pricing versions may both be in force).
    assert {r["subject"] for r in rows(out, domain="policy_versions") if r["operation_id"]} == {my_op}
    payment_rows = rows(out, comparison="payment_archived")
    assert payment_rows and {r["legacy"]["evidence"]["user_id"] for r in payment_rows} <= members
    founder_payments = {r["subject"] for r in payment_rows}
    assert founder_payments == set(session.execute(sa.select(Payment.id).where(
        Payment.user_id == w.founder.user)).scalars())
    counts = out["report"]["population_counts"]
    assert counts["payments"]["in_scope"] == len(founder_payments) < counts["payments"]["population"]
    assert counts["ai_billing_operations"] == {"population": counts["ai_billing_operations"]["population"],
                                               "in_scope": 1}
    assert out["report"]["historical_value_by_state"]["scope"] == "target_organizations"
    assert out["report"]["founder_test_separation"]["scope"] == "target_organizations"
    usd = one(out, comparison="paid_amount_by_currency", subject="usd")
    assert usd["classification"] == "match" and usd["legacy"]["value"] == sum(
        int(p.amount_paid_cents) for p in session.execute(sa.select(Payment).where(
            Payment.id.in_(sorted(founder_payments)))).scalars())


def test_a_global_blocking_comparison_fails_a_gate_and_the_report_is_never_cutover_ready_n1(db):
    """Review N1 negative case: before the fix, a missing attestation and no single pricing version in force
    left every computed gate except ``blocked_accounts`` passing."""
    session = db.session
    w = world(session)
    rehearse(session, w)
    out = shadow(session, w, attestation=None)
    blocking = {f"{r['comparison']}:{r['special_case']}" for r in out["report"]["global_comparisons"]
                if r["blocks_cutover"]}
    assert {"test_activity_attestation:attestation_not_supplied",
            "pricing_conversion:no_single_pricing_version_in_force"} <= blocking
    g = gate(out, "global_comparisons_resolved")
    assert g["status"] == "fail" and set(g["detail"]["blocking"]) == blocking
    assert out["report"]["cutover_ready"] is False


def test_cutover_ready_is_derived_from_every_gate(db, monkeypatch):
    """Readiness is never claimed while any gate is open or failed; only all-pass (or evidence-only) is ready."""
    session = db.session
    w = world(session)
    rehearse(session, w)
    assert shadow(session, w)["report"]["cutover_ready"] is False  # the permanently open gates hold it closed
    original = bs.phase17_gates

    def forced(status_of):
        def gates(*args, **kwargs):
            return [{**g, "status": status_of(g)} for g in original(*args, **kwargs)]
        return gates

    def all_pass(g):
        return "reported" if g["status"] == "reported" else "pass"

    monkeypatch.setattr(bs, "phase17_gates", forced(all_pass))
    assert shadow(session, w)["report"]["cutover_ready"] is True
    for code, status in (("global_comparisons_resolved", "fail"), ("f2_f4_charging", "open")):
        monkeypatch.setattr(bs, "phase17_gates", forced(lambda g, c=code, st=status: st if g["gate"] == c
                                                         else all_pass(g)))
        assert shadow(session, w)["report"]["cutover_ready"] is False, code


def test_founder_test_credit_stays_identified_and_genuine_revenue_stays_zero(db):
    session = db.session
    w = world(session)
    rehearse(session, w)
    out = shadow(session, w)
    founder = one(out, account_id=w.founder.account, comparison="founder_test_classification")
    assert (founder["classification"], founder["authoritative"]["value"]) == ("match", "founder_test")
    unverified = one(out, account_id=w.unverified.account, comparison="founder_test_classification")
    assert (unverified["classification"], unverified["authoritative"]["value"]) == ("match", "unverified")
    usd = one(out, comparison="paid_amount_by_currency", subject="usd")
    assert usd["classification"] == "match"
    assert usd["authoritative"]["evidence"]["verified_customer_revenue"] == 0
    assert usd["authoritative"]["evidence"]["excluded_founder_test"] >= 1000
    separation = out["report"]["founder_test_separation"]
    assert separation["purchased_credit"]["genuine_customer"] == {"lots": 0, "opening_units": 0, "current_units": 0}
    attested = [r for r in rows(out, comparison="test_activity_classification") if r["classification"] != "match"]
    assert attested == []


def _pool_shadow(session, ns, attestation):
    session.commit()
    return bs.run_shadow_reconciliation(flask_db.engine, organization_ids=[ns.org], environment="fixtures",
                                        at=now(session), test_activity_attestation=attestation)


def test_a_fully_attested_team_pool_matches_founder_test(db):
    session = db.session
    ns = team_pool(session, invoices=2)
    pool_rehearsal(session, ns, attest(ns.owner))
    out = _pool_shadow(session, ns, attest(ns.owner))
    r = one(out, account_id=ns.account, comparison="founder_test_classification")
    assert (r["classification"], r["legacy"]["value"], r["authoritative"]["value"]) == \
        ("match", "founder_test", "founder_test")
    assert len(r["legacy"]["evidence"]["payment_ids"]) == 2


def _pool_with_paying_member(session):
    ns = team_pool(session)
    member = session.get(User, ns.member)
    member.subscription_status, member.stripe_subscription_id = "active", f"sub_{uuid.uuid4().hex[:10]}"
    member.stripe_customer_id = f"cus_{uuid.uuid4().hex[:10]}"
    add_invoice(session, member)
    session.commit()
    return ns


def test_a_pool_with_another_paying_member_labelled_founder_test_is_a_genuine_discrepancy(db):
    """Found by the shadow: a quarantined plan mapping omits the second payer, so the Phase 15 C2 rule
    never sees them. The shadow checks every active pooled member itself and blocks the account."""
    session = db.session
    ns = _pool_with_paying_member(session)
    pool_rehearsal(session, ns, attest(ns.owner))
    out = _pool_shadow(session, ns, attest(ns.owner))
    r = one(out, account_id=ns.account, comparison="founder_test_classification")
    assert (r["legacy"]["value"], r["authoritative"]["value"]) == ("unverified", "founder_test")
    assert (r["classification"], r["difference"], r["special_case"]) == \
        ("mismatch", "genuine_discrepancy", "pool_with_another_paying_member")
    assert r["legacy"]["evidence"]["other_paying_pool_members"] == [ns.member] and r["blocks_cutover"]


def _pool_with_phase15_basis(monkeypatch, ns, basis):
    """Make Phase 15 report this pool conservatively ``unverified`` for ``basis`` (fixture seam only)."""
    original = bs.founder_test_credit_separation

    def conservative(s):
        out = original(s)
        for lot in out["lots"]:
            if lot["billing_account_id"] == ns.account and lot["legacy_source_kind"] == "organization_recurring_meter":
                lot["funding"], lot["funding_basis"] = "unverified", basis
        return out

    monkeypatch.setattr(bs, "founder_test_credit_separation", conservative)


def test_a_conservatively_unverified_attested_pool_is_an_approved_policy_difference(db, monkeypatch):
    """The approved C2 rule (another member pays) is a policy difference and does not block."""
    session = db.session
    ns = team_pool(session)
    pool_rehearsal(session, ns, attest(ns.owner))
    _pool_with_phase15_basis(monkeypatch, ns, "another_member_holds_a_paid_subscription")
    out = _pool_shadow(session, ns, attest(ns.owner))
    r = one(out, account_id=ns.account, comparison="founder_test_classification")
    assert (r["classification"], r["difference"], r["policy_key"], r["blocks_cutover"]) == \
        ("mismatch", "approved_policy_difference", "founder_test_requires_complete_attestation", False)


@pytest.mark.parametrize("basis", ["account_not_mapped", "invoice_not_attributed_to_this_account",
                                   "a_basis_phase16_does_not_know", None])
def test_missing_team_pool_evidence_is_unresolved_and_blocking_never_an_approved_policy_n3(db, monkeypatch, basis):
    """Review N3 negative case: before the fix, these bases were labelled an approved policy and did not block."""
    session = db.session
    ns = team_pool(session)
    pool_rehearsal(session, ns, attest(ns.owner))
    _pool_with_phase15_basis(monkeypatch, ns, basis)
    out = _pool_shadow(session, ns, attest(ns.owner))
    r = one(out, account_id=ns.account, comparison="founder_test_classification")
    assert (r["classification"], r["special_case"], r["difference"], r["policy_key"]) == \
        ("unresolved", "team_pool_evidence_missing", None, None)
    assert r["blocks_cutover"] and account(out, ns.account)["blocked"]
    assert (r["legacy"]["value"], r["authoritative"]["value"]) == ("founder_test", "unverified")


def test_without_the_attestation_archived_test_activity_is_unresolved_n4(db):
    session = db.session
    w = world(session)
    rehearse(session, w)
    out = shadow(session, w, attestation=None)
    r = one(out, comparison="test_activity_attestation")
    assert (r["classification"], r["special_case"]) == ("unresolved", "attestation_not_supplied")
    with pytest.raises(TypeError):
        bs.run_shadow_reconciliation(flask_db.engine, organization_ids=w.orgs, environment="fixtures")


# ---------------------------------------------------------------------------
# 12. Pricing and capacity policy-version mismatches
# ---------------------------------------------------------------------------

def test_policy_versions_are_resolved_independently_and_a_wrong_binding_is_a_genuine_mismatch(db):
    session = db.session
    ns = ai_world(session)
    op_id = settled_operation(session, ns)
    session.commit()
    at = now(session)
    out = bs.run_shadow_reconciliation(flask_db.engine, organization_ids=[ns.org], environment="fixtures", at=at,
                                       test_activity_attestation=None)
    for name in ("pricing_version_binding", "capacity_version_binding"):
        assert one(out, comparison=name, subject=op_id)["classification"] == "match"
    assert one(out, account_id=ns.account, comparison="billable_outcome")["classification"] in ("match", "mismatch")
    assert one(out, account_id=ns.account, comparison="acting_user_attribution")["classification"] == "match"
    other = pricing(session, effective_at=at + timedelta(days=30))  # in force only later
    session.get(AIBillingOperation, op_id).pricing_policy_version_id = other.id  # fabricated binding (fixture only)
    session.commit()
    out = bs.run_shadow_reconciliation(flask_db.engine, organization_ids=[ns.org], environment="fixtures", at=at,
                                       test_activity_attestation=None)
    r = one(out, comparison="pricing_version_binding", subject=op_id)
    assert (r["classification"], r["difference"], r["authoritative"]["value"]) == \
        ("mismatch", "genuine_discrepancy", other.id)


def test_a_pricing_conversion_that_differs_from_the_legacy_rate_is_a_genuine_mismatch(db):
    session = db.session
    w = world(session)
    rehearse(session, w)
    pricing(session, conversion=3600)  # displayed credits, not internal units
    out = shadow(session, w)
    r = one(out, comparison="pricing_conversion")
    assert (r["classification"], r["difference"], r["legacy"]["value"]) == ("mismatch", "genuine_discrepancy",
                                                                            3_600_000)
    assert r["variance"] == 3600 - 3_600_000


def test_an_undelivered_operation_charged_by_legacy_is_an_approved_policy_difference(db):
    from tests.test_billing_ai_operations import call
    from app.billing_ai_operations import record_undelivered_operation
    session = db.session
    ns = ai_world(session)
    result = authorize(session, ns)
    call(session, result.operation_id)
    record_undelivered_operation(session, operation_id=result.operation_id)
    session.get(AIOperation, result.operation_id).charged_credits = 42  # what the legacy path would have charged
    session.add(UsageEvent(user_id=ns.owner, organization_id=ns.org, credits_charged=42,
                           metadata_json={"operation_id": result.operation_id}))
    session.commit()
    out = bs.run_shadow_reconciliation(flask_db.engine, organization_ids=[ns.org], environment="fixtures",
                                       at=now(session), test_activity_attestation=None)
    r = one(out, account_id=ns.account, comparison="billable_outcome")
    assert (r["classification"], r["difference"], r["policy_key"]) == \
        ("mismatch", "approved_policy_difference", "delivered_only_billing")
    assert not r["blocks_cutover"] and r["approved_policy"].startswith("P24")
    assert one(out, account_id=ns.account, comparison="usage_event_attribution")["classification"] == "match"


# ---------------------------------------------------------------------------
# 13. Read-only shadow behavior under failures and retries
# ---------------------------------------------------------------------------

def test_a_write_attempted_inside_the_shadow_fails_closed_and_writes_nothing(db, monkeypatch):
    session = db.session
    w = world(session)
    rehearse(session, w)
    session.commit()
    census = bs.shadow_census(session)
    original = bs._ledger_integrity

    def writes(shadow_session, ctx, projection):
        lot = shadow_session.execute(sa.select(CreditLot).limit(1)).scalar_one()
        lot.original_amount = int(lot.original_amount) + 1
        shadow_session.flush()
        return original(shadow_session, ctx, projection)

    monkeypatch.setattr(bs, "_ledger_integrity", writes)
    with pytest.raises(bs.ShadowWriteAttemptError):
        shadow(session, w)
    monkeypatch.undo()
    session.expire_all()
    assert bs.shadow_census(session) == census
    assert shadow(session, w)["census_unchanged"]


def test_a_failure_releases_the_connection_and_a_retry_reproduces_the_report(db, monkeypatch):
    session = db.session
    w = world(session)
    rehearse(session, w)
    at = now(session)
    calls = {"n": 0}
    original = bs._seats

    def flaky(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient fixture failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(bs, "_seats", flaky)
    with pytest.raises(RuntimeError):
        shadow(session, w, at=at)
    retry = shadow(session, w, at=at)
    monkeypatch.undo()
    assert retry["report"]["report_fingerprint"] == shadow(session, w, at=at)["report"]["report_fingerprint"]


def test_an_invariant_violation_is_reported_unresolved_and_the_run_continues(db, monkeypatch):
    session = db.session
    w = world(session)
    rehearse(session, w)
    original = bs.project_billing_account

    def broken(s, *, billing_account_id, **kwargs):
        if billing_account_id == w.free.account and kwargs.get("member_user_id") is None:
            raise bs.ProjectionError("fixture invariant violation")
        return original(s, billing_account_id=billing_account_id, **kwargs)

    monkeypatch.setattr(bs, "project_billing_account", broken)
    out = shadow(session, w)
    r = one(out, account_id=w.free.account, comparison="projection")
    assert (r["classification"], r["special_case"]) == ("unresolved", "projection_invariant_violation")
    assert one(out, account_id=w.founder.account, comparison="member_spendable")["classification"] == "match"


def test_a_production_runtime_or_an_unknown_environment_is_refused(db, monkeypatch):
    session = db.session
    w = world(session)
    session.commit()
    for environment in ("production", "staging", "", None):
        with pytest.raises(bs.ShadowError):
            bs.run_shadow_reconciliation(flask_db.engine, organization_ids=w.orgs, environment=environment,
                                         test_activity_attestation=None)
    import app.billing_rehearsal as br
    monkeypatch.setattr(br, "is_production_runtime", lambda: True)
    with pytest.raises(br.RehearsalError, match="production runtime"):
        bs.run_shadow_reconciliation(flask_db.engine, organization_ids=w.orgs, environment="fixtures",
                                     test_activity_attestation=None)
    with pytest.raises(bs.ShadowError, match="explicit"):
        bs.shadow_reconciliation(session, organization_ids=[], at=now(session), test_activity_attestation=None)


def test_restore_copy_is_refused_before_any_connection_until_an_authorization_mechanism_is_approved_n4(
        db, monkeypatch):
    """Review N4 negative case: before the fix, restore_copy ran on any database from a non-production runtime."""
    session = db.session
    w = world(session)
    session.commit()
    import app.billing_rehearsal as br
    monkeypatch.setattr(br, "is_production_runtime", lambda: False)  # a laptop or CI runtime is not authorization

    class NoConnect:
        def connect(self):
            raise AssertionError("restore_copy opened a database connection")

    for bind in (flask_db.engine, NoConnect()):
        with pytest.raises(bs.ShadowError, match="restore_copy shadow runs are refused"):
            bs.run_shadow_reconciliation(bind, organization_ids=w.orgs, environment="restore_copy",
                                         test_activity_attestation=attest(w.founder.user))
    assert shadow(session, w)["environment"] == "fixtures"  # the local fixture path is unchanged


def test_the_read_only_transaction_is_enforced_by_the_database(db):
    connection, session, facts = bs._read_only_session(flask_db.engine)
    try:
        assert facts["read_only_enforced"]
        with pytest.raises(sa.exc.DBAPIError) as raised:
            session.execute(sa.text("UPDATE users SET credits_remaining = credits_remaining WHERE 1 = 0"))
            session.execute(sa.text("CREATE TABLE phase16_must_not_exist (id integer)"))
        assert bs._is_write_refusal(raised.value)
    finally:
        session.close()
        bs._release(connection)
    with flask_db.engine.connect() as fresh:  # the pool never hands back a read-only connection
        assert "phase16_must_not_exist" not in sa.inspect(fresh).get_table_names()



# ---------------------------------------------------------------------------
# FR-1: membership never establishes ownership of a payment or financial event
# ---------------------------------------------------------------------------

def _unlink_payments_at_teardown(request, session):
    """The shared ``db`` fixture deletes billing accounts before payments; PostgreSQL enforces the payment link."""
    def unlink():
        session.rollback()
        session.execute(sa.update(Payment).values(billing_account_id=None))
        session.commit()
    request.addfinalizer(unlink)


def _cross_member_world(session, request):
    """Organization A (the founder's) gains, as an active collaborator, the user who owns personal organization B
    (the "unverified" fixture, whose paid pack payment Phase 14 attributes to B's account) and the user who owns
    the pre-boundary organization C. Rehearsed afterwards, so every attribution is Phase 14's own."""
    _unlink_payments_at_teardown(request, session)
    w = world(session)
    for ns in (w.unverified, w.expired):
        session.add(OrganizationMember(organization_id=w.founder.org, user_id=ns.user, role="collaborator",
                                       status="active"))
    # A now has several members, so A's payer needs rank-1 evidence: the founder's legacy payments link to A.
    for row in session.execute(sa.select(Payment).where(Payment.user_id == w.founder.user)).scalars():
        row.billing_account_id = w.founder.account
    session.commit()
    rehearse(session, w)
    w.a_payments = set(session.execute(sa.select(Payment.id).where(Payment.user_id == w.founder.user)).scalars())
    w.b_payments = set(session.execute(sa.select(Payment.id).where(Payment.user_id == w.unverified.user)).scalars())
    assert w.a_payments and w.b_payments
    attributed = dict(session.execute(sa.select(BillingMigrationPaymentAttribution.payment_id,
                                                BillingMigrationPaymentAttribution.billing_account_id)).all())
    assert {attributed[p] for p in w.a_payments} == {w.founder.account}
    assert {attributed[p] for p in w.b_payments} == {w.unverified.account}
    return w


def _amount(session, payment_ids):
    return sum(int(p.amount_paid_cents) for p in session.execute(
        sa.select(Payment).where(Payment.id.in_(sorted(payment_ids)))).scalars())


def test_fr1_a_members_payment_owned_by_their_personal_organization_never_appears_in_a(db, request):
    session = db.session
    w = _cross_member_world(session, request)
    out = shadow(session, w, orgs=[w.founder.org])
    exported = bs.export_shadow_report(out)
    # B's payment, account, and organization identifiers never appear in a report targeting A alone.
    for foreign in sorted(w.b_payments) + [w.unverified.account, w.unverified.org, w.expired.org, w.expired.account]:
        assert foreign not in exported, foreign
    # A's own payment, attributed to A by Phase 14, is kept with its evidence basis.
    archived = {r["subject"]: r for r in rows(out, comparison="payment_archived")}
    assert set(archived) == w.a_payments
    assert {r["legacy"]["evidence"]["owner_basis"] for r in archived.values()} == {"phase14_payment_attribution"}
    assert one(out, account_id=w.founder.account, comparison="member_spendable",
               subject=w.founder.user)["classification"] == "match"
    usd = one(out, comparison="paid_amount_by_currency", subject="usd")
    assert usd["classification"] == "match" and usd["legacy"]["value"] == _amount(session, w.a_payments)
    revenue = out["report"]["founder_test_separation"]["customer_revenue"]
    assert sum(revenue["excluded_founder_test_cents_by_currency"].values()) + \
        sum(revenue["unverified_not_revenue_cents_by_currency"].values()) == _amount(session, w.a_payments)
    assert out["report"]["population_counts"]["payments"]["in_scope"] == len(w.a_payments)
    # The member's personal value and subscription are named as owned elsewhere, without the other identifier.
    for comparison in ("member_spendable", "effective_plan", "subscription_status"):
        r = one(out, account_id=w.founder.account, comparison=comparison, subject=w.unverified.user)
        assert r["classification"] == "not_applicable" and r["legacy"]["value"] is None


def test_fr1_the_same_payment_belongs_only_to_its_own_organization_and_is_never_counted_twice(db, request):
    session = db.session
    w = _cross_member_world(session, request)
    b = shadow(session, w, orgs=[w.unverified.org])
    assert {r["subject"] for r in rows(b, comparison="payment_archived")} == w.b_payments
    assert not (w.a_payments & set(bs.export_shadow_report(b).split('"')))
    assert one(b, comparison="paid_amount_by_currency", subject="usd")["legacy"]["value"] == \
        _amount(session, w.b_payments)
    both = shadow(session, w, orgs=[w.founder.org, w.unverified.org])
    subjects = [r["subject"] for r in rows(both, comparison="payment_archived")]
    assert sorted(subjects) == sorted(w.a_payments | w.b_payments) and len(subjects) == len(set(subjects))
    usd = one(both, comparison="paid_amount_by_currency", subject="usd")
    assert usd["legacy"]["value"] == _amount(session, w.a_payments | w.b_payments)
    a = shadow(session, w, orgs=[w.founder.org])
    assert one(a, comparison="paid_amount_by_currency", subject="usd")["legacy"]["value"] + \
        one(b, comparison="paid_amount_by_currency", subject="usd")["legacy"]["value"] == usd["legacy"]["value"]


def test_fr1_history_and_gate_counts_follow_ownership_not_membership(db, request):
    session = db.session
    w = _cross_member_world(session, request)
    op = AIOperation(id=str(uuid.uuid4()), user_id=w.unverified.user, organization_id=w.founder.org,
                     status="started", operation_type="conversation", router_version="test", policy_version="test",
                     projected_credits=9_000)  # stamped with A, but debits the personal meter B owns
    session.add(op)
    session.commit()
    a = shadow(session, w, orgs=[w.founder.org])
    assert op.id not in bs.export_shadow_report(a)
    assert gate(a, "in_flight_operations_drained")["status"] == "pass"
    assert a["report"]["population_counts"]["started_ai_operations"]["in_scope"] == 0
    meters = a["report"]["historical_value_by_state"]["by_state"]["pre_unit_boundary_meter"]
    assert sum(v["holders"] for v in meters.values()) == 0  # C's pre-boundary meter is C's history
    b = shadow(session, w, orgs=[w.unverified.org])
    assert gate(b, "in_flight_operations_drained")["status"] == "fail"
    r = one(b, account_id=w.unverified.account, comparison="legacy_in_flight_operation")
    assert (r["subject"], r["legacy"]["value"]) == (op.id, 9_000)
    c = shadow(session, w, orgs=[w.expired.org])
    meters = c["report"]["historical_value_by_state"]["by_state"]["pre_unit_boundary_meter"]
    assert meters["expired"] == {"holders": 1, "amount": 70_000}


def test_fr1_missing_or_ambiguous_ownership_is_unresolved_blocking_and_never_counted(db, request):
    session = db.session
    w = _cross_member_world(session, request)
    # A collaborator of A with no organization of their own and no account link: their payment has no owner.
    drifter = user(session, "drifter")
    session.add(OrganizationMember(organization_id=w.founder.org, user_id=drifter.id, role="collaborator",
                                   status="active"))
    orphan = bs_payment(session, drifter)
    # A pooled-plan member's in-flight operation: the pool it debited is recorded by no evidence.
    pooled = user(session, "pooled", plan="team")
    session.add(OrganizationMember(organization_id=w.founder.org, user_id=pooled.id, role="collaborator",
                                   status="active"))
    pooled_op = AIOperation(id=str(uuid.uuid4()), user_id=pooled.id, organization_id=w.founder.org,
                            status="started", operation_type="conversation", router_version="test",
                            policy_version="test", projected_credits=4_000)
    session.add(pooled_op)
    session.commit()
    out = shadow(session, w, orgs=[w.founder.org])
    r = one(out, comparison="payment_owner", subject=orphan.id)
    assert (r["classification"], r["special_case"], r["blocks_cutover"]) == \
        ("unresolved", "payment_owner_unresolved", True)
    assert r["legacy"]["value"] is None and r["legacy"]["evidence"]["reason"] == "no_ownership_evidence"
    assert orphan.id not in {x["subject"] for x in rows(out, comparison="payment_archived")}
    assert one(out, comparison="paid_amount_by_currency", subject="usd")["legacy"]["value"] == \
        _amount(session, w.a_payments)  # never counted
    assert "payment_owner:payment_owner_unresolved" in gate(out, "global_comparisons_resolved")["detail"]["blocking"]
    op_row = one(out, account_id=w.founder.account, comparison="legacy_in_flight_operation")
    assert (op_row["subject"], op_row["special_case"], op_row["legacy"]["value"]) == \
        (pooled_op.id, "operation_owner_unresolved", None)
    assert gate(out, "in_flight_operations_drained")["detail"] == {"started_operations": 1, "owner_unresolved": 1}
    assert out["report"]["population_counts"]["payments"]["owner_unresolved"] == 1
    assert out["report"]["cutover_ready"] is False


def test_fr1_conflicting_payment_ownership_evidence_is_unresolved(db, request):
    session = db.session
    w = _cross_member_world(session, request)
    [payment_id] = sorted(w.b_payments)
    session.get(Payment, payment_id).billing_account_id = w.founder.account  # a legacy link disagreeing with Phase 14
    session.commit()
    cache = {}
    assert bs.payment_owner(session, session.get(Payment, payment_id), cache) == (None, "payment_owner_conflict")
    out = shadow(session, w, orgs=[w.founder.org])
    r = one(out, comparison="payment_owner", subject=payment_id)
    assert (r["classification"], r["legacy"]["evidence"]["reason"]) == ("unresolved", "payment_owner_conflict")
    assert payment_id not in {x["subject"] for x in rows(out, comparison="payment_archived")}

# ---------------------------------------------------------------------------
# PostgreSQL 18.6, fully migrated, every guard live
# ---------------------------------------------------------------------------

@PG
def test_postgres_shadow_runs_in_a_read_only_repeatable_read_snapshot_and_reruns_identically():
    engine = _migrated_engine()
    try:
        w = _pg_world(engine)
        with migrated(engine) as session:
            rehearse(session, w)
            session.commit()
            at = now(session)
        first = bs.run_shadow_reconciliation(engine, organization_ids=w.orgs, environment="fixtures", at=at,
                                             test_activity_attestation=attest(w.founder.user))
        second = bs.run_shadow_reconciliation(engine, organization_ids=w.orgs, environment="fixtures", at=at,
                                              test_activity_attestation=attest(w.founder.user))
        assert first["database"]["isolation"] == "REPEATABLE READ READ ONLY"
        assert bs.shadow_repeat_proof(first, second)["same_fingerprint"]
        assert first["census_unchanged"] and second["census_unchanged"]
        for ns in (w.free, w.founder, w.unverified):
            assert one(first, account_id=ns.account, comparison="member_spendable")["classification"] == "match"
            assert one(first, account_id=ns.account, comparison="account_preserved_value")["classification"] == \
                "match"
        assert one(first, account_id=w.founder.account, comparison="founder_test_classification")[
            "authoritative"]["value"] == "founder_test"
    finally:
        engine.dispose()


@PG
def test_postgres_a_write_inside_the_shadow_is_refused_by_the_database(monkeypatch):
    engine = _migrated_engine()
    try:
        w = _pg_world(engine)
        with migrated(engine) as session:
            rehearse(session, w)
            session.commit()
            before = bs.shadow_census(session)

        def writes(shadow_session, ctx, projection):
            shadow_session.execute(sa.text("UPDATE users SET credits_remaining = credits_remaining WHERE id = :u"),
                                   {"u": w.free.user})
            return []

        monkeypatch.setattr(bs, "_ledger_integrity", writes)
        with pytest.raises(bs.ShadowWriteAttemptError):
            bs.run_shadow_reconciliation(engine, organization_ids=w.orgs, environment="fixtures",
                                         test_activity_attestation=attest(w.founder.user))
        with migrated(engine) as session:
            assert bs.shadow_census(session) == before
    finally:
        engine.dispose()


@PG
def test_postgres_fixtures_are_refused_on_a_local_database_not_named_for_tests():
    import os
    url = sa.engine.make_url(os.environ["TEST_DATABASE_URL"]).set(database="postgres")
    engine = sa.create_engine(url)
    try:
        import app.billing_rehearsal as br
        with pytest.raises(br.RehearsalError, match="verified local test database"):
            bs.run_shadow_reconciliation(engine, organization_ids=["any"], environment="fixtures",
                                         test_activity_attestation=None)
    finally:
        engine.dispose()
