"""Phase 14: evidence-backed legacy backfill (D16).

Traceability D16 (step 1 ownership and payers, the opening-balance algorithm,
conservation equations, special cases), D17 T-MIGRATE-01..12 and T-OWNER, D18
row 14, and the Phase 14 acceptance remediation (B1 global source uniqueness,
B2 authoritative sources, original expiration terms, separation of duties).
Legacy fields are set directly on their legacy columns; target records are
built only through the accepted Phase 3-14 commands. Every credit amount is a
test fixture in legacy internal units (1,000 per displayed credit; Gate 1).

ORM-schema tests run on SQLite, or on an isolated PostgreSQL schema when
TEST_DATABASE_URL is set. The ``PG`` tests run on the fully migrated
PostgreSQL 18.6 database (every Phase 3-14 guard live).
"""

from concurrent.futures import ThreadPoolExecutor
import contextlib
from datetime import datetime, timedelta, timezone
import inspect
import os
from pathlib import Path
import threading
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

import app.billing_config as billing_config
import app.billing_migration as bm
from app import db as flask_db
from app.ai_governance import credits_for_provider_cost
from app.billing_entitlements import add_calendar_months
from app.billing_migration import (
    MigrationConflictError,
    MigrationError,
    MigrationPermissionError,
    MigrationRetryError,
    MigrationUnitError,
    archive_legacy_payments,
    backfill_billing_account,
    establish_billing_account,
    historical_value_population,
    legacy_value_inventory,
    map_legacy_plan,
    migration_run_report,
    plan_account_backfill,
    plan_establishment,
    plan_legacy_plan_mapping,
    pricing_unit_findings,
    record_unattributed_review,
    resolve_legacy_value_owner,
    start_migration_run,
    verify_credit_unit_equivalence,
)
from app.billing_offers import record_staff_billing_permission
from app.billing_projections import MATCH, UNRESOLVED, compare_legacy_compatibility
from app.models import (
    AccountEntitlement,
    AIOperation,
    BillingAccount,
    CreditLedgerEntry,
    CreditLot,
    Organization,
    OrganizationMember,
    Payment,
    PersistentCreditGrant,
    PersistentCreditTransaction,
    User,
)
from app.models_billing_phase4 import BillingSubscription, EntitlementInstance
from app.models_billing_phase5 import FinancialTransaction
from app.models_billing_phase14 import (
    BillingMigrationAccountResult,
    BillingMigrationEstablishment,
    BillingMigrationOpening,
    BillingMigrationPayerBinding,
    BillingMigrationPaymentArchive,
    BillingMigrationPaymentAttribution,
    BillingMigrationPlanMapping,
    BillingMigrationRun,
)
from tests.test_billing_ai_operations import account as funded_account
from tests.test_billing_ai_operations import pricing


BACKEND = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = BACKEND / "migrations"
REVISION = "d2f4a6c8e0b3"
PARENT = "c8e0a2b4d6f1"
PHASE14_TABLES = ("billing_migration_plan_mappings", "billing_migration_payment_archives",
                  "billing_migration_openings", "billing_migration_reviews", "billing_migration_account_results",
                  "billing_migration_payment_attributions", "billing_migration_payer_bindings",
                  "billing_migration_establishments", "billing_migration_runs")
PG = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="local disposable PostgreSQL is not configured")
PROVISIONER = {"actor_type": "system", "actor_id": "phase14-provisioning"}
FREE, TEAM = 300_000, 29_000_000  # legacy catalog monthly limits (internal units)


class Ns:
    def __init__(self, **values):
        self.__dict__.update(values)


def now(session):
    return bm._database_clock(session)


def naive(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def meter(remaining, limit, reset, overage=0):
    return {"thinking_power": {"remaining": remaining, "cycle_limit": limit, "overage_tokens": overage,
                               "tokens_used_this_month": max(0, limit - remaining),
                               "cycle_reset_at": naive(reset).isoformat()}}


def user(session, label, *, plan="free", credits=0, reset=None, prefs=None, customer=None):
    row = User(
        id=f"p14-{label}-{uuid.uuid4().hex[:8]}", email=f"p14-{label}-{uuid.uuid4().hex[:8]}@example.test",
        name=f"Phase 14 {label}", password_hash="not-a-login-credential", subscription_plan=plan,
        credits_remaining=credits, credits_reset_at=naive(reset) if reset else None, ui_preferences=prefs,
        stripe_customer_id=customer, seat_limit=1, max_seats=1,
    )
    session.add(row)
    session.flush()
    return row


def organization(session, owner, *, plan_key="team", members=(), statuses=None, customer=None, settings=None,
                 status="active", account=True):
    suffix = uuid.uuid4().hex[:10]
    org = Organization(id=f"p14-org-{suffix}", name=f"P14 {suffix}", slug=f"p14-{suffix}",
                       owner_user_id=owner.id, plan_key=plan_key, settings=settings)
    session.add(org)
    session.flush()
    for member in (owner, *members):
        session.add(OrganizationMember(organization_id=org.id, user_id=member.id,
                                       role="owner" if member is owner else "collaborator",
                                       status=(statuses or {}).get(member.id, "active")))
    session.flush()
    if not account:
        return Ns(org=org.id, account=None)
    row = BillingAccount(id=f"p14-account-{suffix}", organization_id=org.id, currency="usd",
                         account_anchor_at=datetime(2026, 1, 1, tzinfo=timezone.utc), status=status,
                         processor="stripe" if customer else None, processor_customer_id=customer)
    session.add(row)
    session.flush()
    return Ns(org=org.id, account=row.id)


def personal(session, *, remaining=120_000, limit=FREE, days_ago=3, counter=None, plan="free", grants=(),
             customer=None, overage=0):
    """A single-member organization whose only member holds a personal legacy meter."""
    reset = now(session) - timedelta(days=days_ago)
    holder = user(session, "holder", plan=plan, reset=reset, prefs=meter(remaining, limit, reset, overage),
                  customer=customer)
    ns = organization(session, holder, plan_key="free", customer=customer)
    total = remaining + sum(g[1] for g in grants)
    holder.credits_remaining = total if counter is None else counter
    for original, left, *kind in grants:
        grant(session, holder, original, left, **(kind[0] if kind else {}))
    session.flush()
    return Ns(**ns.__dict__, user=holder.id, reset=reset)


def payment(session, holder, *, source="credit_pack", paid=1000, comped=False, reference=None, at=None,
            currency="usd", organization_id=None):
    """A legacy receipt; a payer always has a processor customer (Stripe), so one is assigned when missing."""
    if holder.stripe_customer_id is None:
        holder.stripe_customer_id = f"cus_{uuid.uuid4().hex[:12]}"
    row = Payment(external_reference=reference or f"pi_{uuid.uuid4().hex[:12]}", source=source, user_id=holder.id,
                  amount_paid_cents=0 if comped else paid, amount_due_cents=paid,
                  discount_cents=paid if comped else 0, is_comped=comped, currency=currency,
                  paid_at=naive(at or now(session) - timedelta(days=10)), organization_id=organization_id)
    session.add(row)
    session.flush()
    return row


def grant(session, holder, original, remaining, *, source="credit_pack", paid=1000, comped=False, payment_row=True,
          granted_at=None, reference=None, log_balance=None, reversed_reason=None, organization_id=None):
    reference = reference or f"pi_{uuid.uuid4().hex[:12]}"
    prefix = bm.GRANT_PREFIXES[source]
    granted_at = granted_at or now(session) - timedelta(days=10)
    if payment_row:
        payment(session, holder, source=bm.PAYMENT_SOURCES[source], paid=paid, comped=comped, reference=reference,
                at=granted_at)
    row = PersistentCreditGrant(
        user_id=holder.id, organization_id=organization_id, source=source, original_amount=original,
        remaining_amount=remaining, status="reversed" if reversed_reason else "active",
        external_reference=prefix + reference, granted_at=naive(granted_at),
    )
    session.add(row)
    session.flush()
    session.add(PersistentCreditTransaction(grant_id=row.id, user_id=holder.id, transaction_type="grant",
                                            amount=original, balance_after=original,
                                            created_at=naive(granted_at)))
    used = original - remaining if not reversed_reason else 0
    if used:
        session.add(PersistentCreditTransaction(grant_id=row.id, user_id=holder.id, transaction_type="usage",
                                                amount=-used, balance_after=remaining if log_balance is None
                                                else log_balance, created_at=naive(granted_at) + timedelta(hours=1)))
    if reversed_reason:
        session.add(PersistentCreditTransaction(grant_id=row.id, user_id=holder.id, transaction_type="reversal",
                                                amount=-original, balance_after=0,
                                                transaction_metadata={"reason": reversed_reason},
                                                created_at=naive(granted_at) + timedelta(hours=2)))
    session.flush()
    return row


def operator(session):
    return user(session, "operator")


def run(session, key=None, operator_id=None):
    created, _state = start_migration_run(session, run_key=key or f"run-{uuid.uuid4().hex[:8]}",
                                          authorization_reference="local-fixture-rehearsal",
                                          actor_type="system", actor_id="phase14-test",
                                          operator_user_id=operator_id or operator(session).id)
    return created


def establish(session, ns, migration_run=None):
    row, _state = establish_billing_account(session, run_id=(migration_run or run(session)).id,
                                            organization_id=ns.org)
    return row


def backfill(session, ns, migration_run=None, *, establish_first=True):
    migration_run = migration_run or run(session)
    if establish_first:
        establish(session, ns, migration_run)
    result, _state = backfill_billing_account(session, run_id=migration_run.id, billing_account_id=ns.account)
    return result


def codes(result):
    return sorted({c["code"] for c in result.quarantine_codes_json})


def lots(session, account_id):
    return session.execute(sa.select(CreditLot).where(CreditLot.billing_account_id == account_id)
                           .order_by(CreditLot.source_type, CreditLot.id)).scalars().all()


def entries(session, account_id):
    return session.execute(sa.select(CreditLedgerEntry).where(CreditLedgerEntry.billing_account_id == account_id)
                           ).scalars().all()


def all_openings(session):
    return session.execute(sa.select(BillingMigrationOpening)).scalars().all()


def legacy_snapshot(session):
    users = session.execute(sa.select(User.id, User.credits_remaining, User.credits_reset_at, User.ui_preferences,
                                      User.subscription_plan, User.stripe_customer_id)
                            .where(User.id.not_like("p14-operator-%")).order_by(User.id)).all()
    orgs = session.execute(sa.select(Organization.id, Organization.settings, Organization.plan_key)
                           .order_by(Organization.id)).all()
    grants = session.execute(sa.select(PersistentCreditGrant.id, PersistentCreditGrant.remaining_amount,
                                       PersistentCreditGrant.status).order_by(PersistentCreditGrant.id)).all()
    payments = session.execute(sa.select(Payment.id, Payment.billing_account_id, Payment.organization_id)
                               .order_by(Payment.id)).all()
    return [tuple(r) for r in users], [tuple(r) for r in orgs], [tuple(r) for r in grants], \
        [tuple(r) for r in payments]


def reviewer(session):
    staff = user(session, "reviewer")
    granted, _state = record_staff_billing_permission(
        session, grant_command_id=f"grant-{uuid.uuid4().hex[:10]}", user_id=staff.id,
        permission="billing.migration.review", starts_at=datetime(2020, 1, 1, tzinfo=timezone.utc), ends_at=None,
        approval_evidence_reference="approval:fixture-only", justification="Phase 14 fixture reviewer",
        **PROVISIONER)
    return staff, granted


def review(session, ns, staff, amount, *, command=None, basis="legacy_cycle_end", payment_id=None):
    return record_unattributed_review(
        session, review_command_id=command or f"r-{uuid.uuid4().hex[:8]}", billing_account_id=ns.account,
        subject_user_id=ns.user, amount=amount, expiry_basis=basis, expiry_evidence_payment_id=payment_id,
        expiry_evidence_reference="review:fixture-evidence", candidates_considered=["subscription_recurring",
                                                                                   "credit_pack"],
        reason="counter exceeds every meter and grant; no narrower source is evidenced", reviewer_user_id=staff.id)


# ---------------------------------------------------------------------------
# Gate 1: credit-unit equivalence and the verified pricing unit (R4B)
# ---------------------------------------------------------------------------

def test_gate1_legacy_and_ledger_integers_are_the_same_internal_unit(db):
    evidence = verify_credit_unit_equivalence()
    assert evidence["units_per_displayed_credit"] == billing_config.TOKENS_PER_CREDIT == 1000
    assert evidence["conversion"].startswith("identity")
    # The legacy catalog stores internal units: "3,000 credits" is 3,000,000.
    assert billing_config.DEFAULT_CREDIT_PACKS["credits_3000"]["credits"] == 3000 * 1000
    assert billing_config.tokens_to_credits(FREE, precision=0) == 300
    migration_run = run(db.session)
    assert (migration_run.credit_unit_basis, migration_run.units_per_displayed_credit) == (
        "jaspen.legacy_internal_unit.v1", 1000)


def test_gate1_fails_closed_when_the_unit_identity_no_longer_holds(db, monkeypatch):
    staff = operator(db.session)
    monkeypatch.setattr(bm, "TOKENS_PER_CREDIT", 1)
    with pytest.raises(MigrationUnitError):
        start_migration_run(db.session, run_key="unit-drift", authorization_reference="x",
                            actor_type="system", actor_id="t", operator_user_id=staff.id)
    assert db.session.execute(sa.select(sa.func.count()).select_from(BillingMigrationRun)).scalar_one() == 0


def test_the_provider_dollar_rate_is_3600_displayed_credits_or_3600000_internal_units(db, monkeypatch):
    evidence = verify_credit_unit_equivalence()
    assert (evidence["displayed_credits_per_provider_usd"], evidence["internal_units_per_provider_usd"]) == (
        3600, 3_600_000)
    assert credits_for_provider_cost(1, internal=True) == 3_600_000
    assert credits_for_provider_cost(1, internal=False) == 3600
    monkeypatch.setattr(bm, "credits_for_provider_cost", lambda cost, internal=True: 3600)
    with pytest.raises(MigrationUnitError, match="3600000 internal units"):
        verify_credit_unit_equivalence()


@pytest.mark.parametrize("rate,code", [(3600, "pricing_rate_in_displayed_credits"),
                                       (4000, "pricing_rate_not_the_verified_internal_rate")])
def test_a_run_refuses_an_approved_pricing_version_not_stated_in_internal_units(db, rate, code):
    session = db.session
    staff = operator(session)
    version = pricing(session, conversion=rate)
    assert [(f["code"], f["pricing_policy_version_id"]) for f in pricing_unit_findings(session)] == [(code, version.id)]
    with pytest.raises(MigrationUnitError, match="internal units per provider dollar"):
        start_migration_run(session, run_key=f"pricing-{rate}", authorization_reference="x", actor_type="system",
                            actor_id="t", operator_user_id=staff.id)
    # Customer pricing is never changed here; once that version is superseded by its own process, it no longer blocks.
    pricing(session, conversion=3_600_000)
    assert pricing_unit_findings(session) == []


def test_an_approved_pricing_version_in_internal_units_passes(db):
    session = db.session
    pricing(session, conversion=3_600_000)
    assert pricing_unit_findings(session) == []
    assert run(session).expiry_policy == "original_terms"


# ---------------------------------------------------------------------------
# D16 step 1: billing account, payer, and payment establishment
# ---------------------------------------------------------------------------

def test_establishment_creates_the_missing_account_and_binds_its_payer_and_payments_once(db):
    session = db.session
    owner = user(session, "payer", customer="cus_establish")
    ns = organization(session, owner, plan_key="free", account=False)
    receipts = [payment(session, owner), payment(session, owner, source="limited_time_300k", paid=99_900)]
    before = legacy_snapshot(session)
    first_run = run(session)
    row = establish(session, ns, first_run)
    assert (row.outcome, row.account_created, row.quarantine_codes_json) == ("established", True, [])
    account = session.get(BillingAccount, row.billing_account_id)
    org = session.get(Organization, ns.org)
    assert (account.organization_id, account.status, account.currency) == (ns.org, "proposed", "usd")
    assert bm._utc(account.account_anchor_at) == bm._utc(org.created_at)  # D07 free anchor
    assert (account.processor, account.processor_customer_id) == ("stripe", "cus_establish")
    binding = session.execute(sa.select(BillingMigrationPayerBinding)).scalar_one()
    assert (binding.payer_user_id, binding.billing_account_id, binding.customer_assigned_by_migration) == (
        owner.id, account.id, True)
    attributed = session.execute(sa.select(BillingMigrationPaymentAttribution)
                                 .order_by(BillingMigrationPaymentAttribution.payment_id)).scalars().all()
    assert sorted(a.payment_id for a in attributed) == sorted(p.id for p in receipts)
    assert {(a.amount_paid_cents, a.currency) for a in attributed} == {(1000, "usd"), (99_900, "usd")}
    assert legacy_snapshot(session) == before  # the legacy archive is never written

    # Replay: same evidence, nothing written; the migration's own binding is never read back as evidence.
    replay = establish(session, ns)
    assert (replay.outcome, replay.account_created, replay.billing_account_id) == ("unchanged", False, account.id)
    assert session.execute(sa.select(sa.func.count()).select_from(BillingMigrationPaymentAttribution)
                           ).scalar_one() == 2
    # Changed evidence never moves or adds a binding.
    payment(session, owner)
    changed = establish(session, ns)
    assert changed.outcome == "quarantined" and "evidence_changed_since_establishment" in codes(changed)
    assert session.execute(sa.select(sa.func.count()).select_from(BillingMigrationPaymentAttribution)
                           ).scalar_one() == 2


def test_an_existing_processor_customer_is_external_evidence_and_is_kept(db):
    session = db.session
    owner = user(session, "payer", plan="team", customer="cus_preexisting")
    ns = organization(session, owner, customer="cus_preexisting")
    row = establish(session, ns)
    assert (row.outcome, row.account_created) == ("established", False)
    binding = session.execute(sa.select(BillingMigrationPayerBinding)).scalar_one()
    assert binding.customer_assigned_by_migration is False
    assert resolve_legacy_value_owner(session, owner)["reason"] == "payer_evidence"
    assert establish(session, ns).outcome == "unchanged"


@pytest.mark.parametrize("case,code", [
    ("shared_customer", "shared_processor_customer"),
    ("stamped_elsewhere", "payer_unresolved"),
    ("mixed_currency", "mixed_payment_currencies"),
    ("two_payers", "several_payers_for_account"),
    ("account_customer_differs", "processor_customer_conflict"),
])
def test_establishment_quarantines_conflicting_payer_or_payment_evidence(db, case, code):
    session = db.session
    owner = user(session, "owner", plan="team", customer="cus_owner")
    member = user(session, "member", plan="team")
    ns = organization(session, owner, members=(member,),
                      customer="cus_someone_else" if case == "account_customer_differs" else None)
    if case == "shared_customer":
        member.stripe_customer_id = "cus_owner"
    elif case == "stamped_elsewhere":
        payment(session, owner, organization_id=organization(session, user(session, "other")).org)
    elif case == "mixed_currency":
        payment(session, owner)
        payment(session, owner, currency="eur")
    elif case == "two_payers":
        # Two different payers each carry legacy payment links to this one account (rank 1).
        member.stripe_customer_id = "cus_member"
        payment(session, owner).billing_account_id = ns.account
        payment(session, member).billing_account_id = ns.account
    session.flush()
    row = establish(session, ns)
    assert row.outcome == "quarantined" and code in codes(row), row.quarantine_codes_json
    assert session.execute(sa.select(sa.func.count()).select_from(BillingMigrationPayerBinding)).scalar_one() == 0
    assert session.execute(sa.select(sa.func.count()).select_from(BillingMigrationPaymentAttribution)
                           ).scalar_one() == 0


def test_a_credit_backfill_needs_an_established_account(db):
    session = db.session
    ns = personal(session, remaining=120_000)
    result = backfill(session, ns, establish_first=False)
    assert result.outcome == "quarantined" and "billing_account_not_established" in codes(result)
    assert lots(session, ns.account) == []


# ---------------------------------------------------------------------------
# Recurring, pooled, purchased, promotional, reviewed value (D16 steps 2, 3, 6-8)
# ---------------------------------------------------------------------------

def test_values_from_before_the_unit_boundary_are_never_opened_and_stay_reported(db):
    session = db.session
    ns = personal(session, remaining=0, limit=FREE)
    holder = session.get(User, ns.user)
    grant(session, holder, 5000, 5000, granted_at=datetime(2026, 4, 1, tzinfo=timezone.utc))
    holder.credits_remaining = 5000
    session.flush()
    result = backfill(session, ns)
    assert result.outcome == "quarantined" and "pre_unit_boundary_value" in codes(result)
    assert lots(session, ns.account) == []
    # Not discarded: the purchased value stays on record for a founder decision.
    population = historical_value_population(session)
    assert population["pre_unit_boundary_grant"] == {"holders": 1, "amount": 5000}


def test_a_personal_recurring_remainder_opens_one_member_attributed_lot_to_the_cycle_end(db):
    session = db.session
    ns = personal(session, remaining=120_000)
    before = legacy_snapshot(session)
    result = backfill(session, ns)
    assert result.outcome == "opened" and result.credit_reconciled and codes(result) == []
    (lot,) = lots(session, ns.account)
    assert (lot.source_type, lot.member_attribution_id, lot.original_amount) == ("free_recurring", ns.user, FREE)
    assert bm._utc(lot.expires_at) == add_calendar_months(ns.reset, 1)
    (entry,) = entries(session, ns.account)
    assert (entry.entry_type, entry.available_delta, entry.held_delta) == ("migration_opening", 120_000, 0)
    opening = session.execute(sa.select(BillingMigrationOpening)).scalar_one()
    assert (opening.lot_id, opening.ledger_entry_id, opening.evidence_rank) == (lot.id, entry.id, 3)
    assert opening.expiry_basis == "legacy_cycle_end"
    conservation = result.conservation_json
    assert conservation["balance_exact"] and conservation["target_available_plus_held"] == 120_000
    assert conservation["accepted_legacy_recurring_remaining"] == 120_000
    # Credit fields match the ledger; the plan field still needs the entitlement records (founder boundary).
    assert result.comparison_json["credit_fields_matched"] >= 2
    assert not result.cutover_eligible
    assert {i["field"] for i in result.comparison_json["unresolved"]} & {"users.subscription_plan"}
    assert legacy_snapshot(session) == before  # no legacy field is written


def test_a_pooled_organization_meter_opens_one_unattributed_lot_not_one_per_member(db):
    session = db.session
    reset = now(session) - timedelta(days=2)
    owner = user(session, "owner", plan="team", credits=1_000_000, customer="cus_pool")
    member = user(session, "member", plan="team", credits=1_000_000)
    ns = organization(session, owner, members=(member,), settings=meter(1_000_000, TEAM, reset), customer="cus_pool")
    result = backfill(session, ns)
    assert result.outcome == "opened", result.quarantine_codes_json
    (lot,) = lots(session, ns.account)
    assert (lot.source_type, lot.member_attribution_id, lot.original_amount) == ("subscription_recurring", None, TEAM)
    assert result.conservation_json["target_available_plus_held"] == 1_000_000
    counters = [i for i in result.comparison_json["unresolved"] if i["field"] == "users.credits_remaining"]
    assert counters == []  # each member's counter is a known copy of the pool


def test_expired_recurring_value_is_never_opened(db):
    session = db.session
    ns = personal(session, remaining=50_000, days_ago=40)
    result = backfill(session, ns)
    assert result.outcome == "unchanged" and result.credit_reconciled
    assert lots(session, ns.account) == []
    (source,) = [s for s in result.evidence_json["sources"] if s["kind"] == "user_recurring_meter"]
    assert (source["classification"], source["expired_amount"]) == ("expired_recurring_value", 50_000)


def test_overage_in_a_lapsed_cycle_expired_with_it_and_in_a_live_cycle_quarantines(db):
    session = db.session
    lapsed = personal(session, remaining=50_000, days_ago=40, overage=3_000_000, counter=50_000)
    result = backfill(session, lapsed)
    assert "overage_in_recurring_meter" not in codes(result) and lots(session, lapsed.account) == []
    (source,) = [s for s in result.evidence_json["sources"] if s["kind"] == "user_recurring_meter"]
    assert (source["classification"], source["expired_amount"]) == ("expired_recurring_value", 3_050_000)
    live = personal(session, remaining=50_000, overage=3_000_000)
    assert "overage_in_recurring_meter" in codes(backfill(session, live))


# ---------------------------------------------------------------------------
# Original purchased-credit terms (R3, founder decision 2026-11-18)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("source,comped,lot_source", [
    ("credit_pack", False, "credit_pack_purchase"),
    ("300k_limited_time", False, "credit_pack_purchase"),
    ("300k_limited_time", True, "promotional"),
])
def test_purchased_packs_and_the_300k_offer_keep_their_original_non_expiring_terms(db, source, comped, lot_source):
    session = db.session
    original = 300_000_000 if source == "300k_limited_time" else 3_000_000
    ns = personal(session, remaining=0, grants=[(original, original - 1_750_000,
                                                 {"comped": comped, "source": source})])
    result = backfill(session, ns)
    assert result.outcome == "opened", result.quarantine_codes_json
    (lot,) = lots(session, ns.account)
    assert (lot.source_type, lot.original_amount, lot.expires_at, lot.member_attribution_id) == (
        lot_source, original, None, ns.user)
    assert sum(e.available_delta for e in entries(session, ns.account)) == original - 1_750_000
    (opening,) = all_openings(session)
    grant_row = session.execute(sa.select(PersistentCreditGrant)).scalar_one()
    assert (opening.legacy_source_id, opening.expiry_basis, opening.expires_at) == (
        grant_row.id, "non_expiring_legacy_contract", None)
    assert opening.evidence_json["expiry_evidence"] == bm.NON_EXPIRING_LEGACY_CONTRACTS[source]
    principal = result.conservation_json["purchased_principal_by_source"]
    assert list(principal.values()) == [{"target_original": original, "legacy_original": original}]
    money = result.conservation_json["money_by_currency"]["usd"]
    assert (money["amount_paid_cents"], money["discount_cents"]) == ((0, 1000) if comped else (1000, 0))


def test_a_grant_source_without_established_terms_quarantines_and_no_expiry_is_invented(db):
    session = db.session
    ns = personal(session, remaining=0)
    holder = session.get(User, ns.user)
    row = PersistentCreditGrant(user_id=holder.id, source="founder_gift", original_amount=2_000_000,
                                remaining_amount=2_000_000, status="active", external_reference="gift:fixture",
                                granted_at=naive(now(session) - timedelta(days=2)))
    session.add(row)
    session.flush()
    session.add(PersistentCreditTransaction(grant_id=row.id, user_id=holder.id, transaction_type="grant",
                                            amount=2_000_000, balance_after=2_000_000))
    holder.credits_remaining = 2_000_000
    session.flush()
    result = backfill(session, ns)
    assert result.outcome == "quarantined" and "expiry_terms_unestablished" in codes(result)
    assert lots(session, ns.account) == []


def test_a_grant_without_a_date_is_grant_date_missing_not_pre_boundary(db):
    session = db.session
    ns = personal(session, remaining=0, grants=[(3_000_000, 3_000_000)])
    holder = session.get(User, ns.user)
    account = session.get(BillingAccount, ns.account)
    org = session.get(Organization, ns.org)
    item = bm._holder_evidence(session, holder)["grants"][0]
    item["granted_at"] = None
    _source, found, opening = bm._grant_source(item, holder, account, org, now(session))
    assert "grant_date_missing" in found and "pre_unit_boundary_value" not in found and opening is None


def test_no_migration_expiry_policy_but_original_terms_can_exist(db):
    session = db.session
    assert not hasattr(bm, "PERSISTENT_EXPIRY_POLICIES") and not hasattr(bm, "APPROVED_PERSISTENT_EXPIRY_POLICY")
    assert "expiry_policy" not in inspect.signature(start_migration_run).parameters
    migration_run = run(session)
    savepoint = session.begin_nested()
    with pytest.raises(sa.exc.IntegrityError):
        session.execute(sa.update(BillingMigrationRun).where(BillingMigrationRun.id == migration_run.id)
                        .values(expiry_policy="current_term_end"))
        session.flush()
    savepoint.rollback()
    # A grant opening with an invented expiry violates the opening classification.
    ns = personal(session, remaining=0, grants=[(3_000_000, 3_000_000)])
    backfill(session, ns)
    (opening,) = all_openings(session)
    savepoint = session.begin_nested()
    with pytest.raises(sa.exc.IntegrityError):
        session.execute(sa.insert(BillingMigrationOpening).values(
            **{c.name: getattr(opening, c.name) for c in BillingMigrationOpening.__table__.columns
               if c.name not in ("id", "opening_key", "lot_id", "ledger_entry_id", "idempotency_registry_id",
                                 "legacy_source_id", "expires_at")},
            id=str(uuid.uuid4()), opening_key="forged", lot_id=str(uuid.uuid4()), ledger_entry_id=str(uuid.uuid4()),
            idempotency_registry_id=opening.idempotency_registry_id, legacy_source_id="other",
            expires_at=now(session) + timedelta(days=30)))
    savepoint.rollback()


# ---------------------------------------------------------------------------
# Quarantine of contradictory evidence (D16 special cases)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("case,code", [
    ("log_mismatch", "persistent_grant_log_mismatch"),
    ("chargeback", "legacy_dispute_state_unknown"),
    ("no_payment", "payment_evidence_missing"),
    ("foreign_org", "grant_organization_conflict"),
    ("future", "grant_in_future"),
])
def test_contradictory_or_missing_grant_evidence_quarantines(db, case, code):
    session = db.session
    ns = personal(session, remaining=0)
    holder = session.get(User, ns.user)
    options = {
        "log_mismatch": {"log_balance": 999},
        "chargeback": {"reversed_reason": "stripe_chargeback"},
        "no_payment": {"payment_row": False},
        "foreign_org": {"organization_id": organization(session, user(session, "other")).org},
        "future": {"granted_at": now(session) + timedelta(days=1)},
    }[case]
    remaining = 0 if case == "chargeback" else 2_000_000
    grant(session, holder, 3_000_000, remaining, **options)
    holder.credits_remaining = remaining
    session.flush()
    result = backfill(session, ns)
    assert result.outcome == "quarantined" and code in codes(result)
    assert lots(session, ns.account) == []


def test_one_payment_behind_two_grants_is_a_duplicate_reference_not_double_funding(db):
    session = db.session
    ns = personal(session, remaining=0)
    holder = session.get(User, ns.user)
    grant(session, holder, 3_000_000, 3_000_000, reference="pi_shared")
    grant(session, holder, 300_000_000, 300_000_000, source="300k_limited_time", reference="pi_shared",
          payment_row=False)
    holder.credits_remaining = 303_000_000
    session.flush()
    result = backfill(session, ns)
    assert "duplicate_external_reference" in codes(result) and lots(session, ns.account) == []


def test_a_negative_legacy_meter_quarantines_and_creates_no_debt(db):
    session = db.session
    ns = personal(session, remaining=-4000, counter=-4000)
    result = backfill(session, ns)
    assert "negative_legacy_meter" in codes(result)
    assert lots(session, ns.account) == [] and entries(session, ns.account) == []


def test_a_counter_below_proven_purchased_value_quarantines(db):
    session = db.session
    ns = personal(session, remaining=0, grants=[(3_000_000, 3_000_000)], counter=1_000_000)
    result = backfill(session, ns)
    assert result.outcome == "quarantined"
    assert any(c.startswith("comparison:users.credits_remaining:counter_below_proven_purchased") for c in codes(result))
    assert lots(session, ns.account) == []


def test_historical_counters_without_evidence_stay_quarantined_and_are_reported(db):
    session = db.session
    holder = user(session, "old-counter", credits=7_000)  # pre-boundary value lived here, in old units
    ns = organization(session, holder, plan_key="free")
    migration_run = run(session)
    result = backfill(session, Ns(**ns.__dict__, user=holder.id), migration_run)
    assert result.outcome == "quarantined" and "legacy_meter_absent" in codes(result)
    report = migration_run_report(session, run_id=migration_run.id)
    assert report["historical_value_population"]["legacy_meter_absent"] == {"holders": 1, "amount": 7_000}
    assert lots(session, ns.account) == []


# ---------------------------------------------------------------------------
# Reviewed legacy_unattributed and separation of duties (D16 step 7, R3, section 6)
# ---------------------------------------------------------------------------

def test_a_counter_above_all_evidence_needs_a_review_then_opens_exact_legacy_unattributed(db):
    session = db.session
    ns = personal(session, remaining=100_000, counter=130_000)
    first = backfill(session, ns)
    assert any("counter_above_evidence" in c for c in codes(first)) and lots(session, ns.account) == []

    staff, _grant = reviewer(session)
    with pytest.raises(MigrationError, match="exactly"):
        review(session, ns, staff, 29_999)
    with pytest.raises(MigrationPermissionError):
        review(session, ns, session.get(User, ns.user), 30_000)
    with pytest.raises(MigrationPermissionError):
        review(session, ns, user(session, "no-grant"), 30_000)
    approved, state = review(session, ns, staff, 30_000, command="r-ok")
    assert state == "inserted" and approved.expiry_basis == "legacy_cycle_end"
    assert bm._utc(approved.expires_at) == add_calendar_months(ns.reset, 1)  # the live cycle's end, never chosen
    assert review(session, ns, staff, 30_000, command="r-ok")[1] == "duplicate"

    second = backfill(session, ns)
    assert second.outcome == "opened", second.quarantine_codes_json
    unattributed = [lot for lot in lots(session, ns.account) if lot.source_type == "legacy_unattributed"]
    assert [(lot.original_amount, lot.member_attribution_id) for lot in unattributed] == [(30_000, ns.user)]
    assert bm._utc(unattributed[0].expires_at) == add_calendar_months(ns.reset, 1)
    assert second.conservation_json["approved_migration_adjustments"] == 30_000
    assert second.conservation_json["target_available_plus_held"] == 130_000
    opening = session.execute(sa.select(BillingMigrationOpening).where(
        BillingMigrationOpening.review_id == approved.id)).scalar_one()
    assert (opening.evidence_rank, opening.expiry_basis) == (6, "legacy_cycle_end")


def test_a_review_no_longer_applies_once_the_evidence_changes(db):
    session = db.session
    ns = personal(session, remaining=100_000, counter=130_000)
    staff, _grant = reviewer(session)
    review(session, ns, staff, 30_000)
    holder = session.get(User, ns.user)
    holder.credits_remaining = 140_000
    session.flush()
    result = backfill(session, ns)
    assert result.outcome == "quarantined" and lots(session, ns.account) == []


def test_migration_review_separation_of_duties(db):
    session = db.session
    ns = personal(session, remaining=100_000, counter=130_000)
    org_member = user(session, "member-reviewer")
    session.add(OrganizationMember(organization_id=ns.org, user_id=org_member.id, role="admin", status="active"))
    session.flush()
    record_staff_billing_permission(
        session, grant_command_id=f"grant-{uuid.uuid4().hex[:10]}", user_id=org_member.id,
        permission="billing.migration.review", starts_at=datetime(2020, 1, 1, tzinfo=timezone.utc), ends_at=None,
        approval_evidence_reference="approval:fixture-only", justification="beneficiary member", **PROVISIONER)
    with pytest.raises(MigrationPermissionError, match="beneficiary"):
        review(session, ns, org_member, 30_000)
    session.execute(sa.delete(OrganizationMember).where(OrganizationMember.user_id == org_member.id))
    session.flush()

    staff, _grant = reviewer(session)
    approved, _state = review(session, ns, staff, 30_000)
    # One review per evidence: a second, conflicting approval is refused.
    with pytest.raises(MigrationConflictError, match="already has a review"):
        review(session, ns, org_member, 30_000)
    # The operator of a run cannot consume a review they approved.
    by_reviewer = run(session, operator_id=staff.id)
    refused = backfill(session, ns, by_reviewer)
    assert refused.outcome == "quarantined" and "reviewer_is_run_operator" in codes(refused)
    assert lots(session, ns.account) == []
    opened = backfill(session, ns)
    assert opened.outcome == "opened"
    assert approved.staff_permission_grant_id == _grant.id and approved.reviewer_user_id == staff.id


def test_a_lapsed_cycle_difference_is_reviewable_net_of_the_lapsed_remainder_with_evidenced_terms(db):
    session = db.session
    ns = personal(session, remaining=50_000, days_ago=40, counter=80_000)
    first = backfill(session, ns)
    assert first.outcome == "quarantined"
    plan = plan_account_backfill(session, billing_account_id=ns.account)
    assert plan["evidence"]["holders"][0]["unexplained_difference"] == 30_000  # 80,000 - 50,000 lapsed
    staff, _grant = reviewer(session)
    with pytest.raises(MigrationError, match="no live legacy cycle"):
        review(session, ns, staff, 30_000)  # no cycle-end evidence exists: never invent an expiry
    with pytest.raises(MigrationError, match="non-expiring legacy purchase"):
        review(session, ns, staff, 30_000, basis="non_expiring_legacy_contract")
    assert lots(session, ns.account) == []  # the quarantine stands until the terms are evidenced


def test_a_receipt_that_appears_after_establishment_blocks_the_backfill_until_reviewed(db):
    session = db.session
    ns = personal(session, remaining=0, grants=[(3_000_000, 3_000_000)])
    assert backfill(session, ns).outcome == "opened"
    payment(session, session.get(User, ns.user))  # new payer evidence after the binding
    stale = backfill(session, ns, establish_first=False)
    assert stale.outcome == "quarantined" and "establishment_evidence_changed" in codes(stale)
    blocked = backfill(session, ns)  # re-establishing quarantines too: a binding is never moved or extended
    assert blocked.outcome == "quarantined" and "establishment_quarantined" in codes(blocked)
    assert len(all_openings(session)) == 1


def test_a_non_expiring_review_needs_an_attributed_purchase_that_funds_no_grant(db):
    session = db.session
    holder = user(session, "holder", credits=0)
    ns = organization(session, holder, plan_key="free")
    reset = now(session) - timedelta(days=40)
    holder.ui_preferences = meter(50_000, FREE, reset)
    holder.credits_reset_at = naive(reset)
    holder.credits_remaining = 80_000
    orphan = payment(session, holder)
    backed = grant(session, holder, 3_000_000, 0)
    session.flush()
    ns = Ns(**ns.__dict__, user=holder.id)
    establish(session, ns)
    staff, _grant = reviewer(session)
    backed_payment = session.execute(sa.select(Payment).where(
        Payment.external_reference == backed.external_reference.split(":", 1)[1])).scalar_one()
    with pytest.raises(MigrationError, match="already funds a persistent grant"):
        review(session, ns, staff, 30_000, basis="non_expiring_legacy_contract", payment_id=backed_payment.id)
    approved, _state = review(session, ns, staff, 30_000, basis="non_expiring_legacy_contract", payment_id=orphan.id)
    assert (approved.expires_at, approved.expiry_evidence_payment_id) == (None, orphan.id)
    result = backfill(session, ns)
    assert result.outcome == "opened", result.quarantine_codes_json
    (lot,) = [lot for lot in lots(session, ns.account) if lot.source_type == "legacy_unattributed"]
    assert (lot.original_amount, lot.expires_at) == (30_000, None)


# ---------------------------------------------------------------------------
# Ownership (D16 step 1, T-OWNER): payer evidence, pooled owner, sole member, never the active org
# ---------------------------------------------------------------------------

def test_payer_evidence_owns_personal_value_and_the_active_organization_is_never_evidence(db):
    session = db.session
    payer = user(session, "payer", plan="team", customer="cus_payer")
    team = organization(session, payer, customer="cus_payer", settings=None)
    elsewhere = organization(session, user(session, "elsewhere-owner"))
    payer.active_organization_id = elsewhere.org
    grant(session, payer, 3_000_000, 3_000_000)
    payer.credits_remaining = 3_000_000
    session.flush()
    owner = resolve_legacy_value_owner(session, payer)
    assert (owner["billing_account_id"], owner["reason"]) == (team.account, "payer_evidence")
    result = backfill(session, team)
    assert result.outcome == "opened", result.quarantine_codes_json
    assert [lot.member_attribution_id for lot in lots(session, team.account)] == [payer.id]
    assert lots(session, elsewhere.account) == []


def test_an_active_organization_stamp_on_a_payment_is_a_veto_not_evidence(db):
    session = db.session
    ns = personal(session, remaining=0)
    holder = session.get(User, ns.user)
    other = organization(session, user(session, "other"))
    grant(session, holder, 3_000_000, 3_000_000)
    payment(session, holder, organization_id=other.org)
    holder.credits_remaining = 3_000_000
    session.flush()
    assert resolve_legacy_value_owner(session, holder)["reason"] == "payment_organization_conflict"
    result = backfill(session, ns)
    assert result.outcome == "quarantined" and lots(session, ns.account) == [] and lots(session, other.account) == []


def test_a_member_whose_personal_value_belongs_to_their_own_organization_is_not_compared_in_the_team(db):
    session = db.session
    reset = now(session) - timedelta(days=1)
    owner = user(session, "team-owner", plan="team", credits=0)
    member = user(session, "free-member", plan="free", credits=80_000, reset=reset, prefs=meter(80_000, FREE, reset))
    team = organization(session, owner, members=(member,))
    own = organization(session, member, plan_key="free")
    assert resolve_legacy_value_owner(session, member)["billing_account_id"] == own.account
    team_result = backfill(session, team)
    assert lots(session, team.account) == []
    assert member.id in {item["user_id"] for item in team_result.evidence_json["owned_elsewhere"]}
    assert any(n["subject"] == member.id and "another organization" in n["reason"]
               for n in team_result.comparison_json["not_applicable"])
    own_result = backfill(session, own)
    assert own_result.outcome == "opened"
    assert [lot.original_amount for lot in lots(session, own.account)] == [FREE]


def test_value_without_ownership_evidence_is_quarantined(db):
    session = db.session
    reset = now(session) - timedelta(days=1)
    owner = user(session, "owner", plan="team")
    member = user(session, "orphan", plan="free", credits=80_000, reset=reset, prefs=meter(80_000, FREE, reset))
    team = organization(session, owner, members=(member,))
    result = backfill(session, team)
    assert ("ambiguous_owner", member.id) in {(c["code"], c["subject"]) for c in result.quarantine_codes_json}
    assert lots(session, team.account) == []


def test_value_of_a_former_member_owned_here_is_quarantined_not_stranded(db):
    session = db.session
    owner = user(session, "owner", plan="team")
    former = user(session, "former", plan="team", customer="cus_former")
    team = organization(session, owner, members=(former,), statuses={former.id: "removed"}, customer="cus_former")
    grant(session, former, 3_000_000, 3_000_000)
    former.credits_remaining = 3_000_000
    session.flush()
    result = backfill(session, team)
    assert "attributed_member_not_active" in codes(result) and lots(session, team.account) == []


def test_an_enterprise_label_without_an_executed_contract_quarantines(db):
    session = db.session
    owner = user(session, "enterprise", plan="enterprise_custom", credits=None)
    ns = organization(session, owner, plan_key="enterprise_custom")
    result = backfill(session, ns)
    assert "enterprise_without_contract" in codes(result)


# ---------------------------------------------------------------------------
# B1: one legacy source funds at most one opening, across every billing account (R1)
# ---------------------------------------------------------------------------

def test_b1_the_audited_double_funding_scenario_opens_the_grant_once(db):
    """Acceptance audit B1, reproduced: value opened in A, then payer evidence names team B."""
    session = db.session
    holder = user(session, "holder", customer="cus_b1")
    a = organization(session, holder, plan_key="free")
    grant(session, holder, 4_000_000, 4_000_000)
    holder.credits_remaining = 4_000_000
    session.flush()
    first = backfill(session, a)
    assert first.outcome == "opened", first.quarantine_codes_json
    assert sum(e.available_delta for e in entries(session, a.account)) == 4_000_000

    team_owner = user(session, "team-owner", plan="team")
    b = organization(session, team_owner, members=(holder,))
    # Step 2 as audited: B's account cannot carry the payer's customer, already bound to A.
    savepoint = session.begin_nested()
    with pytest.raises(sa.exc.IntegrityError):
        session.execute(sa.update(BillingAccount).where(BillingAccount.id == b.account)
                        .values(processor="stripe", processor_customer_id="cus_b1"))
        session.flush()
    savepoint.rollback()
    # Payer evidence that does name B (a legacy payment link) now conflicts with the pinned binding.
    session.execute(sa.update(Payment).where(Payment.user_id == holder.id).values(billing_account_id=b.account))
    session.flush()
    b_result = backfill(session, b)
    assert b_result.outcome == "quarantined" and lots(session, b.account) == []
    assert {"ambiguous_owner", "establishment_quarantined"} <= set(codes(b_result))
    a_rerun = backfill(session, a)
    assert a_rerun.outcome == "quarantined"
    # Exactly one opening of the grant exists anywhere, and the ledger holds its value once.
    assert len(all_openings(session)) == 1
    assert session.execute(sa.select(sa.func.sum(CreditLedgerEntry.available_delta)).where(
        CreditLedgerEntry.entry_type == "migration_opening")).scalar_one() == 4_000_000
    report = migration_run_report(session, run_id=first.run_id)
    assert report["sources_opened_more_than_once"] == []

    # Even a direct write of A's opening into B, bypassing planning, is refused by the global source rule.
    (opening,) = all_openings(session)
    planned = [{
        "opening_key": f"migration-opening:{b.account}:persistent_credit_grant:{opening.legacy_source_id}",
        "legacy_source_kind": "persistent_credit_grant", "legacy_source_id": opening.legacy_source_id,
        "lot_source_type": "credit_pack_purchase", "member_attribution_id": holder.id,
        "original_amount": 4_000_000, "opening_amount": 4_000_000, "available_at": opening.available_at,
        "expires_at": None, "expiry_basis": "non_expiring_legacy_contract", "evidence_rank": 1, "review_id": None,
        "expiry_evidence": "forged", "source_fingerprint": "f" * 64,
    }]
    savepoint = session.begin_nested()
    with pytest.raises(bm._SourceAlreadyOpened):
        bm._write_openings(session, session.get(BillingMigrationRun, first.run_id), b_result,
                           {"billing_account_id": b.account, "openings": planned,
                            "unit": verify_credit_unit_equivalence()}, now(session))
    savepoint.rollback()


def test_a_legacy_source_opened_elsewhere_quarantines_when_ownership_evidence_moves(db):
    session = db.session
    a = personal(session, remaining=120_000)  # no processor customer: nothing is bound
    assert backfill(session, a).outcome == "opened"
    holder = session.get(User, a.user)
    team_owner = user(session, "team-owner", plan="team")
    b = organization(session, team_owner, members=(holder,))
    # A later legacy payment link names B (rank 1), so ownership evidence now points at B.
    session.add(Payment(external_reference=f"in_{uuid.uuid4().hex[:10]}", source="subscription_invoice",
                        user_id=holder.id, billing_account_id=b.account, amount_paid_cents=0, amount_due_cents=0,
                        currency="usd", paid_at=naive(now(session))))
    session.flush()
    assert resolve_legacy_value_owner(session, holder)["organization_id"] == b.org
    result = backfill(session, b)
    assert result.outcome == "quarantined" and "legacy_source_opened_elsewhere" in codes(result)
    assert lots(session, b.account) == [] and len(all_openings(session)) == 1


# ---------------------------------------------------------------------------
# Phase 13 compatibility: zero meters and accepted behavior without Phase 14 evidence (R4A)
# ---------------------------------------------------------------------------

def test_a_zero_live_meter_matches_only_with_phase14_evidence(db):
    session = db.session
    ns = personal(session, remaining=0)
    field = "users.ui_preferences.thinking_power.remaining"

    def classification(**kwargs):
        report = compare_legacy_compatibility(session, billing_account_id=ns.account, **kwargs)
        (item,) = [i for i in report["comparisons"] if i["field"] == field]
        return item["classification"]

    assert classification() == UNRESOLVED  # accepted Phase 13 behavior without Phase 14 evidence
    result = backfill(session, ns)
    assert (result.outcome, result.credit_reconciled) == ("unchanged", True)
    assert [list(item) for item in result.evidence_json["zero_cycles"]] == [[field, ns.user]]
    assert classification(zero_cycles=[(field, ns.user)]) == MATCH
    assert classification() == UNRESOLVED


def test_a_zero_meter_that_is_not_a_verified_live_cycle_never_clears_a_blocker(db):
    session = db.session
    future = personal(session, remaining=0, days_ago=-3)  # reset in the future: not a live cycle
    result = backfill(session, future)
    # Not verified, so the accepted Phase 13 classification stands: the zero meter remains an unresolved blocker.
    assert result.outcome == "quarantined" and not result.credit_reconciled
    assert "comparison:users.ui_preferences.thinking_power.remaining:counter_above_evidence" in codes(result)
    assert result.evidence_json["zero_cycles"] == []


# ---------------------------------------------------------------------------
# In-flight work, existing target funding, tenant isolation
# ---------------------------------------------------------------------------

def test_an_in_flight_legacy_operation_quarantines_and_no_hold_is_inferred(db):
    session = db.session
    ns = personal(session, remaining=120_000)
    session.add(AIOperation(id=str(uuid.uuid4()), user_id=ns.user, organization_id=ns.org, status="started",
                            operation_type="conversation", router_version="test", policy_version="test"))
    session.flush()
    result = backfill(session, ns)
    assert "legacy_operation_in_flight" in codes(result)
    assert entries(session, ns.account) == []


def test_existing_target_funding_is_never_funded_twice(db):
    session = db.session
    ns = funded_account(session, credits=500)  # a Phase 6 recurring lot already funds this account
    holder = session.get(User, ns.owner)
    reset = now(session) - timedelta(days=1)
    holder.subscription_plan, holder.credits_remaining, holder.credits_reset_at = "free", 400, naive(reset)
    holder.ui_preferences = meter(400, 500, reset)
    session.flush()
    before = len(entries(session, ns.account))
    result = backfill(session, Ns(account=ns.account, org=ns.org))
    assert result.outcome == "quarantined" and "conservation_mismatch" in codes(result)
    assert len(entries(session, ns.account)) == before
    assert result.conservation_json["pre_existing_target_lots"] == [ns.lot.id]


def test_accounts_are_isolated_and_each_opens_only_its_own_value(db):
    session = db.session
    first, second = personal(session, remaining=100_000), personal(session, remaining=70_000)
    backfill(session, first)
    assert lots(session, second.account) == []
    backfill(session, second)
    assert [lot.billing_account_id for lot in lots(session, first.account)] == [first.account]
    assert sum(e.available_delta for e in entries(session, second.account)) == 70_000


# ---------------------------------------------------------------------------
# Idempotency, changed evidence, atomicity, purity
# ---------------------------------------------------------------------------

def test_replaying_the_same_evidence_creates_zero_entries_and_changed_evidence_quarantines(db):
    session = db.session
    ns = personal(session, remaining=120_000)
    migration_run = run(session)
    first = backfill(session, ns, migration_run)
    again, state = backfill_billing_account(session, run_id=migration_run.id, billing_account_id=ns.account)
    assert (again.id, state) == (first.id, "duplicate")
    replay = backfill(session, ns)
    assert (replay.outcome, replay.opened_count, replay.credit_reconciled) == ("unchanged", 0, True)
    assert replay.evidence_json["decision_reason"] == "already_opened"
    assert len(entries(session, ns.account)) == 1
    holder = session.get(User, ns.user)
    holder.ui_preferences = meter(90_000, FREE, ns.reset)
    holder.credits_remaining = 90_000
    session.flush()
    changed = backfill(session, ns)
    assert changed.outcome == "quarantined" and "evidence_changed_since_opening" in codes(changed)
    assert len(entries(session, ns.account)) == 1


def test_a_failure_mid_opening_leaves_nothing_and_a_retry_succeeds(db, monkeypatch):
    session = db.session
    ns = personal(session, remaining=120_000, grants=[(3_000_000, 3_000_000)])
    migration_run = run(session)
    session.commit()
    original, calls = bm.append_entry, []

    def failing(session_, entry):
        calls.append(entry.id)
        if len(calls) == 4:  # the second opening of the final (non-probe) write
            raise RuntimeError("injected failure")
        return original(session_, entry)

    monkeypatch.setattr(bm, "append_entry", failing)
    with pytest.raises(RuntimeError):
        backfill(session, ns, migration_run)
    session.rollback()
    assert lots(session, ns.account) == [] and entries(session, ns.account) == []
    assert session.execute(sa.select(sa.func.count()).select_from(BillingMigrationAccountResult)).scalar_one() == 0
    assert session.execute(sa.select(sa.func.count()).select_from(BillingMigrationEstablishment)).scalar_one() == 0
    monkeypatch.setattr(bm, "append_entry", original)
    result = backfill(session, ns, migration_run)
    assert result.outcome == "opened" and len(entries(session, ns.account)) == 2


def test_planning_and_reports_are_pure_reads(db):
    session = db.session
    ns = personal(session, remaining=120_000, grants=[(3_000_000, 3_000_000)])
    tables = sorted(flask_db.metadata.tables.values(), key=lambda t: t.name)

    def counts():
        return [session.execute(sa.select(sa.func.count()).select_from(t)).scalar_one() for t in tables]

    before = counts()
    plan = plan_account_backfill(session, billing_account_id=ns.account)
    assert plan == plan_account_backfill(session, billing_account_id=ns.account, at=plan["at"])
    establishment = plan_establishment(session, organization_id=ns.org)
    assert establishment == plan_establishment(session, organization_id=ns.org, at=establishment["at"])
    legacy_value_inventory(session)
    historical_value_population(session)
    pricing_unit_findings(session)
    assert counts() == before and not session.new and not session.dirty


def test_the_run_report_covers_every_holder_and_blocks_the_global_write_cutover(db):
    session = db.session
    ns = personal(session, remaining=120_000)
    orphan_reset = now(session) - timedelta(days=1)
    user(session, "orphan", credits=10_000, reset=orphan_reset, prefs=meter(10_000, FREE, orphan_reset))
    migration_run = run(session)
    backfill(session, ns, migration_run)
    report = migration_run_report(session, run_id=migration_run.id)
    assert report["outcomes"] == {"opened": 1, "unchanged": 0, "quarantined": 0}
    assert report["establishment_outcomes"] == {"established": 1, "unchanged": 0, "quarantined": 0}
    assert report["opened_by_source"] == {"free_recurring": 120_000}
    assert report["sources_opened_more_than_once"] == []
    assert (report["expiry_policy"], report["operator_user_id"]) == ("original_terms", migration_run.operator_user_id)
    assert any(h["billing_account_id"] is None for h in report["uncovered_holders"])
    assert report["global_write_cutover_blocked"]


def test_only_the_trusted_migration_actor_with_an_identified_operator_starts_a_run(db):
    staff = operator(db.session)
    with pytest.raises(MigrationPermissionError):
        start_migration_run(db.session, run_key="k", authorization_reference="a", actor_type="user", actor_id="u",
                            operator_user_id=staff.id)
    with pytest.raises(MigrationPermissionError, match="operator"):
        start_migration_run(db.session, run_key="k", authorization_reference="a", actor_type="system",
                            actor_id="u", operator_user_id="nobody")
    with pytest.raises(MigrationError):
        backfill_billing_account(db.session, run_id="missing", billing_account_id="missing")
    with pytest.raises(MigrationError):
        establish_billing_account(db.session, run_id="missing", organization_id="missing")


def test_phase14_backfill_has_no_live_callers():
    """Inactive: no route, job, webhook, startup, or runtime module names the backfill."""
    callers = sorted(
        str(path.relative_to(BACKEND)) for path in (BACKEND / "app").rglob("*.py")
        if path.name not in {"billing_migration.py", "models_billing_phase14.py", "models.py", "billing_projections.py",
                              "billing_rehearsal.py"}  # Phase 15 rehearsal is inactive
        and ("billing_migration" in path.read_text() or "models_billing_phase14" in path.read_text())
    )
    assert callers == []
    scripts = [p for p in (BACKEND / "scripts").rglob("*.py") if "billing_migration" in p.read_text()]
    assert scripts == []


# ---------------------------------------------------------------------------
# Legacy payment archive and plan mappings (founder decisions 2026-11-18)
# ---------------------------------------------------------------------------

FOUNDER_TESTS = "founder-decision:2026-11-18:historical-paid-activity-was-founder-testing"


def attest(*holders):
    return {"reference": FOUNDER_TESTS, "payer_user_ids": [h if isinstance(h, str) else h.id for h in holders]}


def archive(session, migration_run=None, attestation=None):
    return archive_legacy_payments(session, run_id=(migration_run or run(session)).id,
                                   test_activity_attestation=attestation)


def map_plan(session, ns, migration_run=None):
    row, _state = map_legacy_plan(session, run_id=(migration_run or run(session)).id, billing_account_id=ns.account)
    return row


def subscribe(session, ns, *, plan="essential", status="active", subscription="sub_fixture", invoices=1):
    holder = session.get(User, ns.user)
    holder.subscription_plan, holder.subscription_status = plan, status
    holder.stripe_subscription_id = subscription
    for _ in range(invoices):
        row = payment(session, holder, source="subscription_invoice", paid=3900)
        row.plan_key, row.billing_interval, row.stripe_subscription_id = plan, "month", subscription or "sub_ended"
    session.flush()
    return holder


def phase45_rows(session):
    return [session.execute(sa.select(sa.func.count()).select_from(model)).scalar_one()
            for model in (BillingSubscription, EntitlementInstance, FinancialTransaction)]


def test_with_no_payments_nothing_is_archived_and_a_free_account_maps_free_with_its_credit_preserved(db):
    ns = personal(db.session, remaining=120_000)
    migration_run = run(db.session)
    report = archive(db.session, migration_run)
    assert (report["archived"], report["unchanged"], report["findings"]) == (0, 0, [])
    assert db.session.execute(sa.select(BillingMigrationPaymentArchive)).scalars().all() == []
    result = backfill(db.session, ns, migration_run)
    assert result.outcome == "opened" and int(result.opened_total) == 120_000
    mapping = map_plan(db.session, ns, migration_run)
    assert (mapping.outcome, mapping.legacy_plan_key, mapping.unresolved_json, mapping.quarantine_codes_json) == \
        ("mapped", "free", [], [])
    (subject,) = mapping.mapping_json["subjects"]
    assert (subject["user_id"], subject["mapping"], subject["subscription"], subject["payments"]) == \
        (ns.user, "free", None, [])
    assert mapping.mapping_json["seats"]["paid_seats"] == "none"
    assert mapping.mapping_json["credit_balances"] == {"account_result_id": result.id, "run_id": migration_run.id,
                                                       "outcome": "opened", "opened_total": 120_000}
    # No artificial records: no subscription, entitlement instance, or financial transaction.
    assert phase45_rows(db.session) == [0, 0, 0]


def test_every_payment_is_archived_exactly_once_and_test_activity_needs_a_named_payer(db):
    founder = personal(db.session)
    other = personal(db.session)
    founder_user, other_user = db.session.get(User, founder.user), db.session.get(User, other.user)
    tested = payment(db.session, founder_user, paid=1000, comped=True)
    tested.promotion_code = "FOUNDERTEST100"
    kept = payment(db.session, other_user, paid=2500)
    db.session.flush()
    before = legacy_snapshot(db.session)
    report = archive(db.session, attestation=attest(founder_user))
    assert (report["archived"], report["unchanged"], report["findings"]) == (2, 0, [])
    rows = {r.payment_id: r for r in db.session.execute(sa.select(BillingMigrationPaymentArchive)).scalars()}
    assert (rows[tested.id].classification, rows[tested.id].classification_reference) == ("test_activity",
                                                                                         FOUNDER_TESTS)
    assert (rows[kept.id].classification, rows[kept.id].classification_reference) == ("unverified", None)
    for live in (tested, kept):
        copied = rows[live.id]
        for column in ("external_reference", "source", "currency", "amount_paid_cents", "amount_due_cents",
                       "discount_cents", "is_comped", "promotion_code", "plan_key", "billing_interval",
                       "stripe_subscription_id", "paid_at"):
            assert getattr(copied, column) == getattr(live, column), column
        assert (copied.legacy_user_id, copied.legacy_created_at) == (live.user_id, live.created_at)
        assert copied.unresolved_json == list(bm.PAYMENT_ARCHIVE_UNRESOLVED)
    summary = report["summary"]
    assert summary["verified_customer_payments"] == 0 and summary["unarchived_payments"] == 0
    assert summary["by_classification"]["test_activity"] == {"payments": 1, "amount_paid_cents_by_currency": {"usd": 0}}
    assert summary["by_classification"]["unverified"] == {"payments": 1,
                                                          "amount_paid_cents_by_currency": {"usd": 2500}}
    # Replays never rewrite: the same evidence is unchanged; a different attestation is reported, not applied.
    assert archive(db.session)["archived"] == 0
    replay = archive(db.session, attestation=attest(other_user))
    assert (replay["archived"], replay["unchanged"]) == (0, 2)
    assert sorted(f["code"] for f in replay["findings"]) == ["classification_differs_from_archive"] * 2
    assert {r.payment_id: r.classification for r in
            db.session.execute(sa.select(BillingMigrationPaymentArchive)).scalars()} == \
        {tested.id: "test_activity", kept.id: "unverified"}
    assert legacy_snapshot(db.session) == before
    assert phase45_rows(db.session) == [0, 0, 0]


@pytest.mark.parametrize("attestation", [
    {"reference": FOUNDER_TESTS, "payer_user_ids": []},
    {"reference": FOUNDER_TESTS, "payer_user_ids": "p14-someone"},
    {"reference": FOUNDER_TESTS, "payer_user_ids": ["p14-no-such-user"]},
    {"reference": " ", "payer_user_ids": ["x"]},
    {"reference": FOUNDER_TESTS, "payer_user_ids": ["a", "a"]},
    {"reference": FOUNDER_TESTS, "payer_user_ids": ["a"], "all_payers": True},
])
def test_a_test_activity_attestation_names_its_payers_explicitly(db, attestation):
    with pytest.raises(MigrationError):
        archive(db.session, attestation=attestation)
    assert db.session.execute(sa.select(BillingMigrationPaymentArchive)).scalars().all() == []


def test_a_changed_payment_row_is_reported_and_its_archive_is_never_rewritten(db):
    ns = personal(db.session)
    row = payment(db.session, db.session.get(User, ns.user), paid=1000)
    migration_run = run(db.session)
    archive(db.session, migration_run)
    row.amount_paid_cents = 900
    db.session.flush()
    report = archive(db.session, migration_run)
    assert [f["code"] for f in report["findings"]] == ["archived_payment_changed"]
    stored = db.session.execute(sa.select(BillingMigrationPaymentArchive)).scalar_one()
    assert stored.amount_paid_cents == 1000
    establish(db.session, ns, migration_run)
    assert "archived_payment_changed" in codes(map_plan(db.session, ns, migration_run))


def test_a_live_paid_subscription_maps_with_its_dates_seats_and_payment_details_unresolved(db):
    ns = personal(db.session)
    holder = subscribe(db.session, ns)
    migration_run = run(db.session)
    archive(db.session, migration_run, attest(holder))
    establish(db.session, ns, migration_run)
    mapping = map_plan(db.session, ns, migration_run)
    assert (mapping.outcome, mapping.legacy_plan_key) == ("mapped_pending_processor", "essential")
    assert sorted(u["field"] for u in mapping.unresolved_json) == sorted(bm.SUBSCRIPTION_UNRESOLVED)
    assert {u["reason"] for u in mapping.unresolved_json} == {"requires_processor_verification"}
    (subject,) = mapping.mapping_json["subjects"]
    assert subject["mapping"] == "paid_subscription_unverified"
    assert subject["subscription"]["processor_subscription_id"] == "sub_fixture"
    assert subject["subscription"]["funded_only_by_test_activity"] is True
    assert mapping.mapping_json["seats"]["paid_seats"] == "unresolved"
    assert mapping.mapping_json["organization_plan"]["synced_to_owner"] is False  # the legacy sync is lazy
    assert phase45_rows(db.session) == [0, 0, 0]
    report = migration_run_report(db.session, run_id=migration_run.id)
    assert report["plan_mapping_outcomes"] == {"mapped": 0, "mapped_pending_processor": 1, "quarantined": 0}
    assert report["payment_archive"]["by_classification"]["test_activity"]["payments"] == 1
    assert report["global_write_cutover_blocked"] is True


def _entitle(session, ns, key):
    session.add(AccountEntitlement(user_id=ns.user, entitlement_key=key, source="fixture",
                                   external_reference=f"ent-{uuid.uuid4().hex[:10]}"))
    session.flush()


@pytest.mark.parametrize("case,code", [
    ("paid_label_without_subscription", "plan_without_subscription_evidence"),
    ("free_with_live_subscription", "subscription_state_conflict"),
    ("paid_with_ended_subscription", "subscription_state_conflict"),
    ("paid_without_status", "subscription_status_missing"),
    ("unknown_plan", "unknown_legacy_plan"),
    ("unknown_entitlement", "unknown_legacy_entitlement"),
    ("payment_not_archived", "payment_not_archived"),
    ("invoices_without_end_state", "subscription_history_without_end_state"),
    ("paid_member_without_owner", "plan_owner_unresolved"),
])
def test_ambiguous_plan_records_quarantine_instead_of_guessing(db, case, code):
    ns = personal(db.session)
    holder = db.session.get(User, ns.user)
    if case == "paid_label_without_subscription":
        holder.subscription_plan = "essential"
    elif case == "free_with_live_subscription":
        subscribe(db.session, ns, plan="free", status="active")
    elif case == "paid_with_ended_subscription":
        subscribe(db.session, ns, status="canceled")
    elif case == "paid_without_status":
        subscribe(db.session, ns, status=None)
    elif case == "unknown_plan":
        holder.subscription_plan = "platinum"
    elif case == "unknown_entitlement":
        _entitle(db.session, ns, "mystery_access")
    elif case == "invoices_without_end_state":
        subscribe(db.session, ns, plan="free", status=None, subscription=None)
    elif case == "paid_member_without_owner":
        member = user(db.session, "member", plan="starter")
        member.stripe_subscription_id, member.subscription_status = "sub_member", "active"
        db.session.add(OrganizationMember(organization_id=ns.org, user_id=member.id, role="collaborator",
                                          status="active"))
    db.session.flush()
    migration_run = run(db.session)
    if case != "payment_not_archived":
        archive(db.session, migration_run)
    else:
        payment(db.session, holder)
    establish(db.session, ns, migration_run)
    mapping = map_plan(db.session, ns, migration_run)
    assert mapping.outcome == "quarantined" and mapping.legacy_plan_key is None
    assert code in codes(mapping)
    assert phase45_rows(db.session) == [0, 0, 0]


def test_an_ended_subscription_maps_free_and_keeps_the_300k_entitlement_and_its_non_expiring_credit(db):
    ns = personal(db.session, remaining=0)
    holder = subscribe(db.session, ns, plan="free", status="canceled", subscription=None)
    offer = grant(db.session, holder, 300_000_000, 250_000_000, source="300k_limited_time", paid=4900)
    holder.credits_remaining = 250_000_000
    _entitle(db.session, ns, "300k_limited_time")
    migration_run = run(db.session)
    archive(db.session, migration_run, attest(holder))
    result = backfill(db.session, ns, migration_run)
    assert result.outcome == "opened", result.quarantine_codes_json
    (lot,) = [lot for lot in lots(db.session, ns.account) if lot.source_type == "credit_pack_purchase"]
    assert (int(lot.original_amount), lot.expires_at, int(result.opened_total)) == (300_000_000, None, 250_000_000)
    mapping = map_plan(db.session, ns, migration_run)
    assert (mapping.outcome, mapping.legacy_plan_key) == ("mapped", "free")
    (subject,) = mapping.mapping_json["subjects"]
    assert subject["mapping"] == "free_after_ended_subscription"
    assert [e["entitlement_key"] for e in subject["entitlements"]] == ["300k_limited_time"]
    assert {p["classification"] for p in subject["payments"]} == {"test_activity"}
    assert offer.remaining_amount == 250_000_000


def test_free_members_without_a_plan_of_their_own_are_listed_not_guessed(db):
    owner = user(db.session, "owner")
    member = user(db.session, "member")
    ns = organization(db.session, owner, plan_key="free", members=(member,))
    migration_run = run(db.session)
    archive(db.session, migration_run)
    establish(db.session, ns, migration_run)
    mapping = map_plan(db.session, ns, migration_run)
    assert (mapping.outcome, mapping.legacy_plan_key) == ("mapped", "free")
    assert mapping.mapping_json["subjects"] == []
    assert sorted(u["user_id"] for u in mapping.mapping_json["free_members_without_own_plan"]) == \
        sorted([owner.id, member.id])


def test_a_plan_mapping_needs_an_established_account_and_replays_to_the_same_row(db):
    ns = personal(db.session)
    migration_run = run(db.session)
    with pytest.raises(MigrationError, match="billing_account_not_established"):
        map_legacy_plan(db.session, run_id=migration_run.id, billing_account_id=ns.account)
    establish(db.session, ns, migration_run)
    before = legacy_snapshot(db.session)
    planned = plan_legacy_plan_mapping(db.session, billing_account_id=ns.account)
    assert db.session.execute(sa.select(BillingMigrationPlanMapping)).scalars().all() == []
    first, state = map_legacy_plan(db.session, run_id=migration_run.id, billing_account_id=ns.account)
    again, replay = map_legacy_plan(db.session, run_id=migration_run.id, billing_account_id=ns.account)
    assert (state, replay, again.id) == ("inserted", "duplicate", first.id)
    assert first.evidence_fingerprint == planned["evidence_fingerprint"]
    db.session.get(User, ns.user).subscription_plan = "essential"
    db.session.flush()
    with pytest.raises(MigrationConflictError):
        map_legacy_plan(db.session, run_id=migration_run.id, billing_account_id=ns.account)
    assert legacy_snapshot(db.session)[1:] == before[1:]


# ---------------------------------------------------------------------------
# Migration: single head, literal checks, SQLite guards and exact restoration of earlier guards
# ---------------------------------------------------------------------------

def _revision():
    from alembic.script import ScriptDirectory
    return ScriptDirectory(str(MIGRATIONS_DIR)).get_revision(REVISION).module


@contextlib.contextmanager
def _ops(engine):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            yield connection


def test_revision_extends_phase12_and_is_the_single_head():
    from alembic.script import ScriptDirectory
    script = ScriptDirectory(str(MIGRATIONS_DIR))
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PARENT


def test_revision_check_constraints_are_literal_copies_of_the_models():
    from app import models_billing_phase14 as models
    module = _revision()
    for name, literal in module.CHECKS.items():
        table = getattr(models, name).__table__
        live = {c.name: str(c.sqltext) for c in table.constraints if isinstance(c, sa.CheckConstraint)}
        assert {n: t for t, n in literal} == live
    assert set(module.TABLES) == set(PHASE14_TABLES)


def _captured_phase10_sqlite_guards():
    """Phase 10's SQLite statements, recorded; its gate rewrite sees a schema already in the target form."""
    from importlib import import_module
    module = import_module("migrations.versions.f2b4d6e8a0c3_add_offer_comp_and_internal_funding")

    class Result:
        def scalar_one(self):
            return module.NEW_GATE

    class Recorder:
        def __init__(self):
            self.statements = []

        def execute(self, statement, *_args, **_kwargs):
            self.statements.append(str(statement))

        def get_bind(self):
            return Ns(execute=lambda *_a, **_k: Result())

    recorder, original = Recorder(), module.op
    module.op = recorder
    try:
        module._sqlite_guards()
    finally:
        module.op = original
    return "\n".join(recorder.statements)


def _earlier_sqlite_lot_triggers():
    """The three earlier lot triggers exactly as their own revisions define them today."""
    phase11 = _revision()._phase11()
    replacements = phase11._sqlite_replacements(phase11._sqlite_originals())
    phase10 = _captured_phase10_sqlite_guards()
    return {
        "trg_phase6_recurring_lot_insert": replacements["trg_phase6_recurring_lot_insert"],
        "trg_phase9_purchase_lot_insert": replacements["trg_phase9_purchase_lot_insert"],
        "trg_phase10_offer_lot_insert": phase11._sqlite_trigger(phase10, "trg_phase10_offer_lot_insert"),
    }


def _sqlite_triggers(connection):
    return dict(connection.execute(sa.text("SELECT name, sql FROM sqlite_master WHERE type='trigger'")).all())


def test_sqlite_migration_guards_and_restores_earlier_triggers_exactly(tmp_path):
    module = _revision()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase14.sqlite'}")
    try:
        flask_db.metadata.create_all(engine, tables=[t for t in flask_db.metadata.sorted_tables
                                                     if t.name not in PHASE14_TABLES])
        earlier = _earlier_sqlite_lot_triggers()
        table, name, old, new = module.PERMISSION_CHECK
        with _ops(engine) as connection:
            module._phase11()._sqlite_replace_check(table, new, old)
            for statement in earlier.values():
                connection.execute(sa.text(statement))
        with engine.connect() as connection:
            before = _sqlite_triggers(connection)
        with _ops(engine):
            module.upgrade()
        with engine.connect() as connection:
            after = _sqlite_triggers(connection)
        assert set(module.SQLITE_TRIGGERS) <= set(after)
        for trigger in earlier:
            assert after[trigger] == before[trigger].replace(
                dict(module.SQLITE_PATCHES)[trigger], dict(module.SQLITE_PATCHES)[trigger] + module.SQLITE_BYPASS)
        with engine.begin() as connection:
            connection.execute(sa.text("PRAGMA foreign_keys=OFF"))
            connection.execute(sa.text(
                "INSERT INTO idempotency_registry (id,namespace,key,request_fingerprint,state,claimed_at) VALUES "
                "('g','billing.migration.opening','k','" + "a" * 64 + "','claimed','2026-11-01')"))
            connection.execute(sa.text(
                "INSERT INTO billing_migration_account_results (id,run_id,billing_account_id,organization_id,outcome,"
                "snapshot_at,evidence_fingerprint,evidence_json,quarantine_codes_json,conservation_json,"
                "comparison_json,opened_count,opened_total,credit_reconciled,cutover_eligible,idempotency_registry_id,"
                "created_at) VALUES ('res','run','a','o','opened','2026-11-01','" + "a" * 64 + "','{}','[]','{}',"
                "'{}',1,5,1,0,'r','2026-11-01')"))
            forged = ("INSERT INTO billing_migration_openings (id,run_id,account_result_id,billing_account_id,"
                      "opening_key,legacy_source_kind,legacy_source_id,lot_id,ledger_entry_id,idempotency_registry_id,"
                      "lot_source_type,member_attribution_id,original_amount,opening_amount,available_at,expires_at,"
                      "expiry_basis,effective_at,evidence_rank,source_fingerprint,evidence_json,created_at) VALUES "
                      "('op','run','res','a','k','persistent_credit_grant','does-not-exist','l','e','g',"
                      "'credit_pack_purchase','u',50000000000,50000000000,'2026-11-01',NULL,"
                      "'non_expiring_legacy_contract','2026-11-01',1,'" + "a" * 64 + "','{}','2026-11-01')")
            with pytest.raises(sa.exc.DBAPIError, match="established billing account"):
                connection.execute(sa.text(forged))
            connection.execute(sa.text(
                "INSERT INTO idempotency_registry (id,namespace,key,request_fingerprint,state,claimed_at) VALUES "
                "('ge','billing.migration.establishment','run:o','" + "a" * 64 + "','claimed','2026-11-01')"))
            connection.execute(sa.text("INSERT INTO billing_accounts (id,organization_id,status,currency,"
                                       "account_anchor_at,created_at,updated_at) VALUES ('a','o','proposed','usd',"
                                       "'2026-01-01','2026-01-01','2026-01-01')"))
            connection.execute(sa.text(
                "INSERT INTO billing_migration_establishments (id,run_id,organization_id,billing_account_id,outcome,"
                "account_created,evidence_fingerprint,evidence_json,quarantine_codes_json,idempotency_registry_id,"
                "created_at) VALUES ('est','run','o','a','established',0,'" + "a" * 64 + "','{}','[]','ge',"
                "'2026-11-01')"))
            with pytest.raises(sa.exc.DBAPIError, match="legacy grant, payment, and payment attribution"):
                connection.execute(sa.text(forged))
            with pytest.raises(sa.exc.DBAPIError, match="legacy_unattributed"):
                connection.execute(sa.text(
                    "INSERT INTO credit_lots (id,billing_account_id,source_type,source_id,original_amount,"
                    "available_at,origin_evidence_json,created_at) VALUES ('l','a','legacy_unattributed','s',5,"
                    "'2026-11-01','{}','2026-11-01')"))
            with pytest.raises(sa.exc.DBAPIError, match="opening evidence"):
                connection.execute(sa.text(
                    "INSERT INTO credit_ledger_entries (id,billing_account_id,lot_id,entry_type,available_delta,"
                    "held_delta,idempotency_registry_id,effective_at,created_at,actor_type,actor_id,reason_code,"
                    "evidence_json) VALUES ('e','a','l','migration_opening',5,0,'i','2026-11-01','2026-11-01',"
                    "'system','t','t','{}')"))
            with pytest.raises(sa.exc.DBAPIError, match="payment attribution must copy"):
                connection.execute(sa.text(
                    "INSERT INTO billing_migration_payment_attributions (id,establishment_id,payer_binding_id,"
                    "billing_account_id,payment_id,external_reference,source,currency,amount_paid_cents,"
                    "amount_due_cents,discount_cents,is_comped,created_at) VALUES ('pa','est','b','a','nope','pi_x',"
                    "'credit_pack','usd',1000,1000,0,0,'2026-11-01')"))
            archive_columns = ("INSERT INTO billing_migration_payment_archives (id,run_id,payment_id,external_reference,"
                               "source,currency,amount_paid_cents,amount_due_cents,discount_cents,is_comped,paid_at,"
                               "legacy_created_at,classification,classification_reference,unresolved_json,"
                               "evidence_fingerprint,idempotency_registry_id,created_at) VALUES ")
            fingerprint = "'" + "a" * 64 + "'"
            connection.execute(sa.text(
                "INSERT INTO payments (id,external_reference,source,amount_paid_cents,amount_due_cents,discount_cents,"
                "currency,is_comped,paid_at,created_at) VALUES ('pay','pi_ok','credit_pack',1000,1000,0,'usd',0,"
                "'2026-11-01 00:00:00.000000','2026-11-01 00:00:00.000000')"))
            connection.execute(sa.text(
                "INSERT INTO idempotency_registry (id,namespace,key,request_fingerprint,state,claimed_at) VALUES "
                "('ga','billing.migration.payment_archive','pay'," + fingerprint + ",'claimed','2026-11-01')"))
            copy = ("'pay','pi_ok','credit_pack','usd',{paid},1000,0,0,'2026-11-01 00:00:00.000000',"
                    "'2026-11-01 00:00:00.000000',{kind},'[]'," + fingerprint + ",'ga','2026-11-01')")
            with pytest.raises(sa.exc.DBAPIError, match="payment archive must copy"):
                connection.execute(sa.text(archive_columns + "('pa','run'," + copy.format(
                    paid=999, kind="'unverified',NULL")))
            with pytest.raises(sa.exc.DBAPIError, match="CHECK constraint failed"):
                connection.execute(sa.text(archive_columns + "('pa','run'," + copy.format(
                    paid=1000, kind="'test_activity',NULL")))
            connection.execute(sa.text(archive_columns + "('pa','run'," + copy.format(
                paid=1000, kind="'unverified',NULL")))
            with pytest.raises(sa.exc.DBAPIError, match="immutable"):
                connection.execute(sa.text(
                    "UPDATE billing_migration_payment_archives SET classification='test_activity'"))
            mapping = ("INSERT INTO billing_migration_plan_mappings (id,run_id,establishment_id,billing_account_id,"
                       "organization_id,outcome,legacy_plan_key,snapshot_at,mapping_json,unresolved_json,"
                       "quarantine_codes_json,evidence_fingerprint,idempotency_registry_id,created_at) VALUES "
                       "('pm','run',{est},'a','o','mapped','free','2026-11-01','{{}}','[]','[]'," + fingerprint
                       + ",'gm','2026-11-01')")
            with pytest.raises(sa.exc.DBAPIError, match="plan mapping requires an established billing account"):
                connection.execute(sa.text(mapping.format(est="'no-such-establishment'")))
            with pytest.raises(sa.exc.DBAPIError, match="plan mapping requires its own idempotency claim"):
                connection.execute(sa.text(mapping.format(est="'est'")))
            connection.execute(sa.text("DELETE FROM payments WHERE id='pay'"))
            connection.execute(sa.text("DELETE FROM billing_accounts WHERE id='a'"))
        with _ops(engine) as connection:
            # Downgrade refuses while evidence exists; the fixture rows are removed below its guard first.
            for trigger in [t for t in module.SQLITE_TRIGGERS if t.endswith("_delete")]:
                connection.execute(sa.text(f"DROP TRIGGER {trigger}"))
            for table in PHASE14_TABLES:
                connection.execute(sa.text(f"DELETE FROM {table}"))
            for trigger, sql in module._sqlite_guards().items():
                if trigger.endswith("_delete"):
                    connection.execute(sa.text(sql))
        with _ops(engine):
            module.downgrade()
        with engine.connect() as connection:
            assert _sqlite_triggers(connection) == before
        assert not set(sa.inspect(engine).get_table_names()) & set(PHASE14_TABLES)
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# PostgreSQL 18.6: fully migrated database, every Phase 3-14 guard live
# ---------------------------------------------------------------------------

def _migrated_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("local disposable PostgreSQL is not configured")
    engine = sa.create_engine(url, pool_size=8, max_overflow=4)
    with engine.connect() as connection:
        revision = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    if revision != REVISION:
        engine.dispose()
        pytest.fail(f"Phase 14 migrated tests require Alembic head {REVISION}; found {revision!r}")
    with migrated(engine) as session:
        # Other phases' fixtures leave effective pricing at fixture rates; a run requires the verified
        # internal-unit rate, so the shared database is put on it through the normal pricing lifecycle.
        if pricing_unit_findings(session):
            pricing(session, conversion=3_600_000)
            session.commit()
    return engine


@contextlib.contextmanager
def migrated(engine, isolation="READ COMMITTED"):
    with Session(engine.execution_options(isolation_level=isolation), expire_on_commit=False) as session:
        yield session


def _pg_personal(engine, **kwargs):
    with migrated(engine) as session:
        ns = personal(session, **kwargs)
        session.commit()
        return ns


def _pg_opened(engine, **kwargs):
    ns = _pg_personal(engine, **kwargs)
    with migrated(engine) as session:
        result = backfill(session, ns)
        session.commit()
        assert result.outcome == "opened", result.quarantine_codes_json
        ns.run, ns.result = result.run_id, result.id
    return ns


@PG
def test_postgres_migrated_backfill_passes_every_guard_and_replays_to_zero_entries():
    engine = _migrated_engine()
    try:
        ns = _pg_opened(engine, remaining=120_000, grants=[(300_000_000, 299_000_000, {"source": "300k_limited_time"})])
        with migrated(engine) as session:
            replay = backfill(session, ns)
            session.commit()
            assert replay.outcome == "unchanged" and len(entries(session, ns.account)) == 2
            by_source = {lot.source_type: lot for lot in lots(session, ns.account)}
            assert int(by_source["free_recurring"].original_amount) == FREE
            assert by_source["credit_pack_purchase"].expires_at is None
    finally:
        engine.dispose()


@PG
def test_postgres_migrated_backfill_requires_read_committed():
    engine = _migrated_engine()
    try:
        ns = _pg_personal(engine)
        with migrated(engine, "REPEATABLE READ") as session:
            with pytest.raises(MigrationError, match="READ COMMITTED"):
                backfill(session, ns)
    finally:
        engine.dispose()


@PG
@pytest.mark.parametrize("statement,match", [
    ("INSERT INTO credit_lots (id,billing_account_id,source_type,source_id,original_amount,available_at,"
     "origin_evidence_json) VALUES ('p14-forged-lot',:account,'legacy_unattributed','x',5,now(),'{}')",
     "legacy_unattributed"),
    ("INSERT INTO credit_lots (id,billing_account_id,source_type,source_id,original_amount,available_at,"
     "expires_at,origin_evidence_json) VALUES ('p14-forged-lot',:account,'subscription_recurring',:opening,5,"
     "now()-interval '1 day',now()+interval '1 day','{}')", "migration lot|recurring lot"),
    # A purchased lot naming a nonexistent grant or opening: the unchanged Phase 9 rule judges it.
    ("INSERT INTO credit_lots (id,billing_account_id,source_type,source_id,original_amount,available_at,"
     "origin_evidence_json) VALUES ('p14-forged-lot',:account,'credit_pack_purchase','no-such-grant',"
     "50000000000,now(),'{}')", "purchase|funding|payment"),
    ("UPDATE billing_migration_openings SET opening_amount=1 WHERE id=:opening", "immutable"),
    ("DELETE FROM billing_migration_account_results", "immutable"),
    ("UPDATE billing_migration_payer_bindings SET billing_account_id=billing_account_id", "immutable"),
    ("DELETE FROM billing_migration_payment_attributions", "immutable"),
    ("TRUNCATE billing_migration_runs CASCADE", "truncated"),
])
def test_postgres_migrated_direct_sql_cannot_forge_or_rewrite_migration_evidence(statement, match):
    engine = _migrated_engine()
    try:
        ns = _pg_opened(engine, grants=[(3_000_000, 3_000_000)])
        with migrated(engine) as session:
            opening = session.execute(sa.select(BillingMigrationOpening.id).where(
                BillingMigrationOpening.billing_account_id == ns.account).limit(1)).scalar_one()
        with engine.connect() as connection:
            with pytest.raises(sa.exc.DBAPIError, match=match):
                with connection.begin():
                    connection.execute(sa.text(statement), {"account": ns.account, "opening": opening})
    finally:
        engine.dispose()


def _forge_chain(connection, ns, *, kind, source_id, amount, original=None, lot_source="credit_pack_purchase",
                 expires_at=None, basis="non_expiring_legacy_contract", member=None, account=None, review_id=None,
                 rank=1):
    """The audited B2 chain, built directly: an opened result, its claims, and an opening (no Phase 14 code)."""
    suffix = uuid.uuid4().hex[:10]
    account = account or ns.account
    org = connection.execute(sa.text("SELECT organization_id FROM billing_accounts WHERE id=:a"),
                             {"a": account}).scalar_one()
    for registry, namespace, key in ((f"rr-{suffix}", "billing.migration.account_result", f"forged:{suffix}"),
                                     (f"ro-{suffix}", "billing.migration.opening", f"forged-opening:{suffix}")):
        connection.execute(sa.text(
            "INSERT INTO idempotency_registry (id,namespace,key,request_fingerprint,state,claimed_at) "
            "VALUES (:id,:ns,:key,:fp,'claimed',now())"), {"id": registry, "ns": namespace, "key": key, "fp": "c" * 64})
    connection.execute(sa.text(
        "INSERT INTO billing_migration_account_results (id,run_id,billing_account_id,organization_id,outcome,"
        "snapshot_at,evidence_fingerprint,evidence_json,quarantine_codes_json,conservation_json,comparison_json,"
        "opened_count,opened_total,credit_reconciled,cutover_eligible,idempotency_registry_id) VALUES "
        "(:id,:run,:account,:org,'opened',now(),:fp,'{}','[]','{}','{}',1,:amount,true,false,:reg)"),
        {"id": f"res-{suffix}", "run": ns.run, "account": account, "org": org, "fp": "c" * 64, "amount": amount,
         "reg": f"rr-{suffix}"})
    connection.execute(sa.text(
        "INSERT INTO billing_migration_openings (id,run_id,account_result_id,billing_account_id,opening_key,"
        "legacy_source_kind,legacy_source_id,lot_id,ledger_entry_id,idempotency_registry_id,lot_source_type,"
        "member_attribution_id,original_amount,opening_amount,available_at,expires_at,expiry_basis,effective_at,"
        "evidence_rank,source_fingerprint,evidence_json,review_id) VALUES (:id,:run,:res,:account,:key,:kind,:source,"
        ":lot,:entry,:reg,:lot_source,:member,:original,:amount,now()-interval '1 day',:expires,:basis,now(),:rank,"
        ":fp,'{}',:review)"),
        {"id": f"op-{suffix}", "run": ns.run, "res": f"res-{suffix}", "account": account,
         "key": f"forged-opening:{suffix}", "kind": kind, "source": source_id, "lot": f"lot-{suffix}",
         "entry": f"entry-{suffix}", "reg": f"ro-{suffix}", "lot_source": lot_source,
         "member": member if member is not None else ns.user, "original": original or amount, "amount": amount,
         "expires": expires_at, "basis": basis, "rank": rank, "fp": "c" * 64, "review": review_id})


@PG
@pytest.mark.parametrize("case,match", [
    ("nonexistent_grant", "legacy grant, payment, and payment attribution"),
    ("grant_without_payment", "legacy grant, payment, and payment attribution"),
    ("grant_payment_not_attributed", "legacy grant, payment, and payment attribution"),
    ("grant_with_invented_expiry", "classification|legacy grant"),
    ("meter_amount_unsupported", "live legacy meter"),
    ("fabricated_review", "equal its review"),
    ("unestablished_account", "established billing account"),
    ("second_opening_of_a_source", "uq_billing_migration_openings_source"),
])
def test_postgres_b2_a_migration_opening_needs_an_authoritative_legacy_source(case, match):
    """Acceptance audit B2, reproduced per variant: internally consistent Phase 14 rows with no legacy evidence."""
    engine = _migrated_engine()
    try:
        ns = _pg_opened(engine, remaining=120_000, grants=[(3_000_000, 3_000_000)])
        with migrated(engine) as session:
            holder = session.get(User, ns.user)
            opened_grant = session.execute(sa.select(PersistentCreditGrant).where(
                PersistentCreditGrant.user_id == holder.id)).scalar_one()
            extra = {}
            if case == "grant_without_payment":
                bare = grant(session, holder, 50_000_000_000, 50_000_000_000, payment_row=False)
                extra["source_id"] = bare.id
            elif case == "grant_payment_not_attributed":
                late = grant(session, holder, 50_000_000_000, 50_000_000_000)  # its payment came after establishment
                extra["source_id"] = late.id
            elif case == "unestablished_account":
                other = organization(session, user(session, "other"))
                extra["account"] = other.account
            ns.run = run(session).id  # a fresh run: the forged result is the account's only one in it
            session.commit()
        params = {
            "nonexistent_grant": dict(kind="persistent_credit_grant", source_id="does-not-exist",
                                      amount=50_000_000_000),
            "grant_without_payment": dict(kind="persistent_credit_grant", amount=50_000_000_000),
            "grant_payment_not_attributed": dict(kind="persistent_credit_grant", amount=50_000_000_000),
            "grant_with_invented_expiry": dict(kind="persistent_credit_grant", source_id="no-such-grant",
                                               amount=3_000_000, expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc)),
            "meter_amount_unsupported": dict(kind="user_recurring_meter", source_id=ns.user, amount=299_000,
                                             original=FREE, lot_source="free_recurring", basis="legacy_cycle_end",
                                             expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc), rank=3),
            "fabricated_review": dict(kind="reviewed_unattributed", source_id="no-review", amount=30_000,
                                      lot_source="legacy_unattributed", basis="non_expiring_legacy_contract",
                                      review_id="no-review", rank=6),
            "unestablished_account": dict(kind="persistent_credit_grant", source_id=opened_grant.id,
                                          amount=3_000_000),
            "second_opening_of_a_source": dict(kind="persistent_credit_grant", source_id=opened_grant.id,
                                               amount=3_000_000),
        }[case]
        params.update(extra)
        with engine.connect() as connection:
            with pytest.raises(sa.exc.DBAPIError, match=match):
                with connection.begin():
                    _forge_chain(connection, ns, **params)
        with migrated(engine) as session:
            assert len(lots(session, ns.account)) == 2
    finally:
        engine.dispose()


@PG
@pytest.mark.parametrize("case,match", [
    ("reviewer_is_member", "member, owner, or payer"),
    ("exceeds_counter", "exceed the subject"),
    ("non_expiring_without_purchase", "non-expiring purchase"),
    ("revoked_or_missing_grant", "review grant"),
])
def test_postgres_a_fabricated_review_is_refused(case, match):
    engine = _migrated_engine()
    try:
        ns = _pg_personal(engine, remaining=100_000, counter=130_000)
        with migrated(engine) as session:
            staff, granted = reviewer(session)
            establish(session, ns)
            if case == "reviewer_is_member":
                session.add(OrganizationMember(organization_id=ns.org, user_id=staff.id, role="admin",
                                               status="active"))
            session.commit()
        rv = f"p14-rv-{uuid.uuid4().hex[:8]}"
        values = {"rv": rv, "account": ns.account, "subject": ns.user, "fp": "b" * 64, "grant": granted.id,
                  "reviewer": staff.id if case != "revoked_or_missing_grant" else ns.user,
                  "amount": 130_001 if case == "exceeds_counter" else 30_000,
                  "basis": "non_expiring_legacy_contract" if case == "non_expiring_without_purchase"
                  else "legacy_cycle_end",
                  "expires": None if case == "non_expiring_without_purchase" else datetime(2027, 1, 1, tzinfo=timezone.utc),
                  "payment": "no-such-payment" if case == "non_expiring_without_purchase" else None}
        with engine.connect() as connection:
            with pytest.raises(sa.exc.DBAPIError, match=match):
                with connection.begin():
                    connection.execute(sa.text(
                        "INSERT INTO idempotency_registry (id,namespace,key,request_fingerprint,state,claimed_at) "
                        "VALUES (:rv,'billing.migration.review',:rv,:fp,'claimed',now())"), values)
                    connection.execute(sa.text(
                        "INSERT INTO billing_migration_reviews (id,review_key,billing_account_id,subject_user_id,"
                        "amount,expiry_basis,expires_at,expiry_evidence_payment_id,expiry_evidence_reference,"
                        "candidates_json,reason,evidence_fingerprint,reviewer_user_id,staff_permission_grant_id,"
                        "reviewed_at,request_fingerprint,idempotency_registry_id) VALUES (:rv,:rv,:account,:subject,"
                        ":amount,:basis,:expires,:payment,'e','[]','r',:fp,:reviewer,:grant,now(),:fp,:rv)"), values)
    finally:
        engine.dispose()


@PG
@pytest.mark.parametrize("case,match", [
    ("binding_customer_mismatch", "payer binding requires"),
    ("attribution_amount_mismatch", "payment attribution must copy"),
    ("second_binding_of_a_payer", "uq_billing_migration_payer_bindings_"),
])
def test_postgres_forged_payer_bindings_and_payment_attributions_are_refused(case, match):
    engine = _migrated_engine()
    try:
        ns = _pg_opened(engine, remaining=0, grants=[(3_000_000, 3_000_000)])
        with migrated(engine) as session:
            binding = session.execute(sa.select(BillingMigrationPayerBinding).where(
                BillingMigrationPayerBinding.billing_account_id == ns.account)).scalar_one()
            attribution = session.execute(sa.select(BillingMigrationPaymentAttribution).where(
                BillingMigrationPaymentAttribution.billing_account_id == ns.account)).scalar_one()
        statement = {
            "binding_customer_mismatch": (
                "INSERT INTO billing_migration_payer_bindings (id,establishment_id,billing_account_id,payer_user_id,"
                "processor,processor_customer_id,customer_assigned_by_migration,evidence_json) VALUES "
                "(:id,:est,:account,:payer,'stripe','cus_forged',true,'{}')"),
            "attribution_amount_mismatch": (
                "INSERT INTO billing_migration_payment_attributions (id,establishment_id,payer_binding_id,"
                "billing_account_id,payment_id,external_reference,source,currency,amount_paid_cents,"
                "amount_due_cents,discount_cents,is_comped) VALUES (:id,:est,:binding,:account,:payment,'pi_forged',"
                "'credit_pack','usd',999999,999999,0,false)"),
            "second_binding_of_a_payer": (
                "INSERT INTO billing_migration_payer_bindings (id,establishment_id,billing_account_id,payer_user_id,"
                "processor,processor_customer_id,customer_assigned_by_migration,evidence_json) VALUES "
                "(:id,:est,:account,:payer,'stripe',:customer,true,'{}')"),
        }[case]
        values = {"id": str(uuid.uuid4()), "est": binding.establishment_id, "account": ns.account,
                  "payer": binding.payer_user_id, "binding": binding.id, "payment": attribution.payment_id,
                  "customer": binding.processor_customer_id}
        with engine.connect() as connection:
            with pytest.raises(sa.exc.DBAPIError, match=match):
                with connection.begin():
                    connection.execute(sa.text(statement), values)
    finally:
        engine.dispose()


@PG
def test_postgres_migrated_migration_opening_entries_and_grants_need_their_evidence():
    engine = _migrated_engine()
    try:
        ns = _pg_opened(engine)
        with migrated(engine) as session:
            lot = lots(session, ns.account)[0]
        with engine.connect() as connection:
            for entry_type in ("migration_opening", "grant"):
                with pytest.raises(sa.exc.DBAPIError, match="migration"):
                    with connection.begin():
                        registry = str(uuid.uuid4())
                        connection.execute(sa.text(
                            "INSERT INTO idempotency_registry (id,namespace,key,request_fingerprint,state,claimed_at)"
                            " VALUES (:id,'fixture',:id,:fp,'claimed',now())"), {"id": registry, "fp": "a" * 64})
                        connection.execute(sa.text(
                            "INSERT INTO credit_ledger_entries (id,billing_account_id,lot_id,entry_type,"
                            "available_delta,held_delta,idempotency_registry_id,effective_at,actor_type,actor_id,"
                            "reason_code,evidence_json) VALUES (:id,:account,:lot,:type,1,0,:registry,now(),"
                            "'system','t','t','{}')"),
                            {"id": str(uuid.uuid4()), "account": ns.account, "lot": lot.id, "type": entry_type,
                             "registry": registry})
    finally:
        engine.dispose()


@PG
@pytest.mark.parametrize("same_run", [True, False])
def test_postgres_concurrent_backfills_of_one_account_open_value_once(same_run):
    engine = _migrated_engine()
    try:
        ns = _pg_personal(engine, remaining=120_000)
        with migrated(engine) as session:
            shared = run(session)
            establish(session, ns, shared)
            session.commit()
        barrier = threading.Barrier(2)

        def attempt(_index):
            with migrated(engine) as session:
                migration_run = shared if same_run else run(session)
                session.commit()
                barrier.wait()
                result, state = backfill_billing_account(session, run_id=migration_run.id,
                                                         billing_account_id=ns.account)
                session.commit()
                return result.outcome, state

        with ThreadPoolExecutor(2) as pool:
            outcomes = sorted(pool.map(attempt, range(2)))
        if same_run:
            assert outcomes == [("opened", "duplicate"), ("opened", "inserted")]
        else:
            assert outcomes == [("opened", "inserted"), ("unchanged", "inserted")]
        with migrated(engine) as session:
            assert sum(e.available_delta for e in entries(session, ns.account)) == 120_000
            assert len(lots(session, ns.account)) == 1
    finally:
        engine.dispose()


@PG
def test_postgres_concurrent_backfills_of_two_accounts_never_open_one_source_twice(monkeypatch):
    """B1 under concurrency: two accounts both claim one member's meter; the database admits one opening."""
    engine = _migrated_engine()
    try:
        with migrated(engine) as session:
            reset = now(session) - timedelta(days=2)
            holder = user(session, "shared", credits=120_000, reset=reset, prefs=meter(120_000, FREE, reset))
            a = organization(session, user(session, "owner-a"), plan_key="free", members=(holder,))
            b = organization(session, user(session, "owner-b"), plan_key="free", members=(holder,))
            shared_run = run(session)
            establish(session, a, shared_run)
            establish(session, b, shared_run)
            session.commit()
        claims = threading.local()
        real = bm.resolve_legacy_value_owner

        def conflicting_claim(session, user_row):
            found = real(session, user_row)
            if user_row.id == holder.id:  # each account's evidence claims the holder (the conflicting attribution)
                return {**found, "organization_id": claims.org, "reason": "conflicting_fixture_claim"}
            return found

        monkeypatch.setattr(bm, "resolve_legacy_value_owner", conflicting_claim)
        barrier = threading.Barrier(2)

        def attempt(ns):
            claims.org = ns.org
            for _try in range(2):
                with migrated(engine) as session:
                    barrier_wait = _try == 0
                    if barrier_wait:
                        barrier.wait()
                    try:
                        result, _state = backfill_billing_account(session, run_id=run(session).id,
                                                                  billing_account_id=ns.account)
                        session.commit()
                        return result.outcome, codes(result)
                    except MigrationRetryError:
                        session.rollback()
            raise AssertionError("no outcome")

        with ThreadPoolExecutor(2) as pool:
            outcomes = list(pool.map(attempt, (a, b)))
        assert sorted(o for o, _c in outcomes) == ["opened", "quarantined"], outcomes
        assert any("legacy_source_opened_elsewhere" in c for o, c in outcomes if o == "quarantined")
        with migrated(engine) as session:
            openings = session.execute(sa.select(BillingMigrationOpening).where(
                BillingMigrationOpening.legacy_source_id == holder.id)).scalars().all()
            assert len(openings) == 1
            assert sum(e.available_delta for e in entries(session, a.account) + entries(session, b.account)) == 120_000
    finally:
        engine.dispose()


@PG
def test_postgres_migrated_review_requires_an_unrevoked_grant_and_read_committed():
    engine = _migrated_engine()
    try:
        ns = _pg_personal(engine, remaining=100_000, counter=130_000)
        command = f"pg-{uuid.uuid4().hex[:8]}"
        with migrated(engine) as session:
            staff, _grant = reviewer(session)
            session.commit()
        with migrated(engine, "REPEATABLE READ") as session:
            with pytest.raises(MigrationError, match="READ COMMITTED"):
                review(session, ns, staff, 30_000, command=command)
        with migrated(engine) as session:
            review(session, ns, staff, 30_000, command=command)
            session.commit()
            result = backfill(session, ns)
            session.commit()
            assert result.outcome == "opened", result.quarantine_codes_json
            assert {lot.source_type for lot in lots(session, ns.account)} == {"free_recurring", "legacy_unattributed"}
    finally:
        engine.dispose()


@PG
def test_postgres_no_migration_reviewer_or_role_exists_by_default():
    engine = _migrated_engine()
    try:
        with engine.connect() as connection:
            assert connection.execute(sa.text(
                "SELECT count(*) FROM pg_roles WHERE rolname LIKE '%billing_migration%'")).scalar_one() == 0
            granted = connection.execute(sa.text(
                "SELECT count(*) FROM billing_staff_permission_grants g WHERE g.permission='billing.migration.review' "
                "AND g.user_id NOT LIKE 'p14-reviewer-%'")).scalar_one()
            assert granted == 0  # only test fixtures ever hold it
    finally:
        engine.dispose()


@PG
def test_postgres_downgrade_restores_the_earlier_guards_byte_for_byte():
    """Round trip on a separate disposable database migrated to the Phase 14 head."""
    url = os.environ.get("TEST_PHASE14_ROUNDTRIP_DATABASE_URL")
    if not url:
        pytest.skip("TEST_PHASE14_ROUNDTRIP_DATABASE_URL is not configured")
    module = _revision()
    engine = sa.create_engine(url)
    names = [name for name, _anchor, _row in module.PG_PATCHES]

    def bodies():
        with engine.connect() as connection:
            return {n: connection.execute(sa.text("SELECT prosrc FROM pg_proc WHERE proname=:n"), {"n": n})
                    .scalar_one() for n in names}

    try:
        patched = bodies()
        assert all("phase14_is_opening_lot" in body for body in patched.values())
        with _ops(engine):
            module.downgrade()
        restored = bodies()
        for name, anchor, row in module.PG_PATCHES:
            assert restored[name] == patched[name].replace(anchor + module.PG_BYPASS.format(row=row), anchor)
            assert "phase14" not in restored[name]
        with engine.connect() as connection:
            assert not connection.execute(sa.text(
                "SELECT count(*) FROM pg_proc WHERE proname LIKE 'phase14_%'")).scalar_one()
        with _ops(engine):
            module.upgrade()
        assert bodies() == patched
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# PostgreSQL 18.6: legacy payment archive and plan mappings under every live guard
# ---------------------------------------------------------------------------

def _pg_archived_and_mapped(engine):
    ns = _pg_personal(engine, grants=[(3_000_000, 3_000_000)])
    with migrated(engine) as session:
        migration_run = run(session)
        report = archive(session, migration_run, attest(ns.user))
        result = backfill(session, ns, migration_run)
        mapping = map_plan(session, ns, migration_run)
        session.commit()
        ns.archive = session.execute(sa.select(BillingMigrationPaymentArchive).where(
            BillingMigrationPaymentArchive.legacy_user_id == ns.user)).scalar_one()
        ns.run, ns.result, ns.mapping, ns.report = migration_run.id, result, mapping, report
    return ns


@PG
def test_postgres_payments_archive_exactly_and_plans_map_with_every_guard_live():
    engine = _migrated_engine()
    try:
        ns = _pg_archived_and_mapped(engine)
        assert ns.result.outcome == "opened", ns.result.quarantine_codes_json
        assert (ns.archive.classification, ns.archive.classification_reference) == ("test_activity", FOUNDER_TESTS)
        assert (ns.mapping.outcome, ns.mapping.legacy_plan_key) == ("mapped", "free")
        assert ns.report["summary"]["verified_customer_payments"] == 0
        with migrated(engine) as session:
            replay = archive(session, attestation=attest(ns.user))
            session.commit()
            assert replay["archived"] == 0
            assert session.execute(sa.select(sa.func.count()).select_from(BillingMigrationPaymentArchive).where(
                BillingMigrationPaymentArchive.legacy_user_id == ns.user)).scalar_one() == 1
            assert session.execute(sa.select(sa.func.count()).select_from(FinancialTransaction).where(
                FinancialTransaction.billing_account_id == ns.account)).scalar_one() == 0
    finally:
        engine.dispose()


ARCHIVE_FORGERY = (
    "INSERT INTO billing_migration_payment_archives (id,run_id,payment_id,external_reference,source,legacy_user_id,"
    "legacy_organization_id,legacy_billing_account_id,currency,amount_paid_cents,amount_due_cents,discount_cents,"
    "is_comped,promotion_code,plan_key,billing_interval,stripe_subscription_id,paid_at,legacy_created_at,"
    "classification,classification_reference,unresolved_json,evidence_fingerprint,idempotency_registry_id) "
    "SELECT :id,:run,{payment},p.external_reference,p.source,p.user_id,p.organization_id,p.billing_account_id,"
    "p.currency,p.amount_paid_cents{delta},p.amount_due_cents,p.discount_cents,p.is_comped,p.promotion_code,"
    "p.plan_key,p.billing_interval,p.stripe_subscription_id,p.paid_at,p.created_at,{kind},'[]',repeat('a',64),"
    ":registry FROM payments p WHERE p.id=:payment"
)
MAPPING_FORGERY = (
    "INSERT INTO billing_migration_plan_mappings (id,run_id,establishment_id,billing_account_id,organization_id,"
    "outcome,legacy_plan_key,snapshot_at,mapping_json,unresolved_json,quarantine_codes_json,evidence_fingerprint,"
    "idempotency_registry_id) VALUES (:id,:run,{establishment},:account,:org,'mapped','essential',now(),'{{}}',"
    "'[]','[]',repeat('a',64),{registry})"
)


@PG
@pytest.mark.parametrize("statement,match", [
    (ARCHIVE_FORGERY.format(payment="p.id", delta="+1", kind="'unverified',NULL"), "payment archive must copy"),
    (ARCHIVE_FORGERY.format(payment="'no-such-payment'", delta="", kind="'unverified',NULL"),
     "payment archive must copy"),
    (ARCHIVE_FORGERY.format(payment="p.id", delta="", kind="'unverified',NULL"),
     "uq_billing_migration_payment_archives_"),
    (ARCHIVE_FORGERY.format(payment="p.id", delta="", kind="'test_activity',NULL"),
     "ck_billing_migration_payment_archives_basis"),
    (MAPPING_FORGERY.format(establishment="'no-such-establishment'", registry=":mapping_registry"),
     "plan mapping requires an established billing account"),
    (MAPPING_FORGERY.format(establishment=":establishment", registry=":registry"),
     "plan mapping requires its own idempotency claim"),
    ("UPDATE billing_migration_payment_archives SET classification='unverified', classification_reference=NULL "
     "WHERE id=:archive", "immutable"),
    ("DELETE FROM billing_migration_plan_mappings WHERE id=:mapping", "immutable"),
    ("TRUNCATE billing_migration_payment_archives", "truncated"),
])
def test_postgres_forged_or_rewritten_payment_archives_and_plan_mappings_are_refused(statement, match):
    engine = _migrated_engine()
    try:
        ns = _pg_archived_and_mapped(engine)
        values = {"id": str(uuid.uuid4()), "run": ns.run, "payment": ns.archive.payment_id,
                  "registry": ns.archive.idempotency_registry_id, "archive": ns.archive.id,
                  "mapping": ns.mapping.id, "mapping_registry": ns.mapping.idempotency_registry_id,
                  "establishment": ns.mapping.establishment_id, "account": ns.account, "org": ns.org}
        with engine.connect() as connection:
            with pytest.raises(sa.exc.DBAPIError, match=match):
                with connection.begin():
                    connection.execute(sa.text(statement), values)
    finally:
        engine.dispose()
