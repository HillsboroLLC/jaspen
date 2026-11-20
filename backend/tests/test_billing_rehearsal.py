"""Phase 15: local rehearsal of the Phase 14 backfill (D16 reconciliation reports, D18 row 15).

Traceability: D18 row 15 (exact reports, failure injection, downgrade and
rollback, rerun no-op); D16 "Reconciliation reports" and "Rollback"; the six
Phase 15 start checks of the Phase 14 re-acceptance; re-acceptance F4
(pre-2026-05-08 value expired and live apart); the founder test-credit policy
(2026-11-19: founder-test credits kept, identifiable, and excluded from
customer revenue and genuine purchased credit; unverified stays unverified).

Fixtures reuse the Phase 14 builders; every target record is written only
by the accepted Phase 14 commands through the rehearsal. ``PG`` tests run on
the fully migrated PostgreSQL 18.6 database with every Phase 3-14 guard live.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import os
from pathlib import Path
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

import app.billing_rehearsal as br
from app import db as flask_db
from app.billing_migration import UNIT_BOUNDARY_AT, MigrationRetryError, historical_value_population
from app.models import AIOperation, CreditLedgerEntry, CreditLot, User
from app.models_billing_phase14 import (
    BillingMigrationEstablishment,
    BillingMigrationOpening,
    BillingMigrationPaymentArchive,
    BillingMigrationPlanMapping,
)
from tests.test_billing_migration import (
    FREE,
    PG,
    TEAM,
    archive,
    organization,
    payment,
    run,
    PHASE14_TABLES,
    _earlier_sqlite_lot_triggers,
    _migrated_engine,
    _ops,
    _revision,
    attest,
    grant,
    meter,
    migrated,
    now,
    operator,
    personal,
    user,
)


BACKEND = Path(__file__).resolve().parents[1]
AUTHORIZATION = "local-fixture-rehearsal"


class World:
    pass


def world(session):
    """A small legacy population covering every rehearsal path (committed)."""
    w = World()
    w.free = personal(session, remaining=120_000)
    w.founder = personal(session, remaining=50_000, grants=[(3_000_000, 2_500_000)])
    w.unverified = personal(session, remaining=40_000, grants=[(3_000_000, 3_000_000)])
    pre_boundary_days = (now(session) - UNIT_BOUNDARY_AT).days + 30
    w.expired = personal(session, remaining=70_000, days_ago=pre_boundary_days)
    w.negative = personal(session, remaining=-5)
    w.operator = operator(session).id
    w.orgs = sorted([w.free.org, w.founder.org, w.unverified.org, w.expired.org, w.negative.org])
    w.accounts = {w.free.account, w.founder.account, w.unverified.account, w.expired.account, w.negative.account}
    session.commit()
    return w


def rehearse(session, w, key=None, **kwargs):
    kwargs.setdefault("test_activity_attestation", attest(w.founder.user))
    return br.run_rehearsal(session, run_key=key or f"r15-{uuid.uuid4().hex[:8]}",
                            authorization_reference=AUTHORIZATION, operator_user_id=w.operator,
                            organization_ids=w.orgs, environment="fixtures", **kwargs)


def ours(rows, w, field="billing_account_id"):
    return [row for row in rows if row[field] in w.accounts]


def finding(preconditions, check):
    return next(f for f in preconditions["findings"] if f["check"] == check)


def counts(session, *models):
    return [session.execute(sa.select(sa.func.count()).select_from(m)).scalar_one() for m in models]


# ---------------------------------------------------------------------------
# Preconditions (the six Phase 15 start checks)
# ---------------------------------------------------------------------------

def test_fixture_preconditions_pass_and_any_other_environment_is_refused(db):
    pre = br.rehearsal_preconditions(db.session, environment="fixtures")
    assert pre["ready"], pre["findings"]
    assert finding(pre, "credit_unit_equivalence")["status"] == "pass"
    assert finding(pre, "pricing_in_internal_units")["status"] == "pass"
    assert finding(pre, "founder_test_credit_policy")["detail"] == br.FOUNDER_TEST_POLICY
    for check in ("legacy_writers_frozen_before_snapshot", "migration_role_least_privilege",
                  "runtime_role_cannot_write_phase14"):
        assert (finding(pre, check)["status"], finding(pre, check)["scope"]) == ("not_applicable", "restore_copy")
    assert {f["check"] for f in pre["findings"] if f["scope"] == "cutover"} == {
        "migration_review_holder", "approved_entitlement_definitions", "pre_unit_boundary_rule",
        "processor_verification"}
    for environment in ("production", "staging", "", None):
        with pytest.raises(br.RehearsalError, match="never production"):
            br.rehearsal_preconditions(db.session, environment=environment)


def test_restore_copy_preconditions_fail_closed_without_the_cutover_controls(db):
    session = db.session
    ns = personal(session, remaining=120_000)
    session.add(AIOperation(id=str(uuid.uuid4()), user_id=ns.user, organization_id=ns.org, status="started",
                            operation_type="conversation", router_version="test", policy_version="test"))
    session.flush()
    fixtures = br.rehearsal_preconditions(session, environment="fixtures")
    # Fixture runs report the operation (its account quarantines); a restore copy must drain it first.
    assert fixtures["ready"] and finding(fixtures, "no_in_flight_ai_operations")["status"] == "reported"
    restore = br.rehearsal_preconditions(session, environment="restore_copy")
    assert not restore["ready"]
    assert finding(restore, "no_in_flight_ai_operations")["status"] == "fail"
    assert finding(restore, "legacy_writers_frozen_before_snapshot")["status"] == "fail"
    if session.get_bind().dialect.name == "sqlite":
        assert finding(restore, "restore_copy_database")["status"] == "fail"
    else:  # the test connection is a superuser, never a migration-only role
        assert finding(restore, "migration_role_least_privilege")["status"] == "fail"
    with pytest.raises(br.RehearsalPreconditionError) as raised:
        br.run_rehearsal(session, run_key="r15-restore", authorization_reference=AUTHORIZATION,
                         operator_user_id=operator(session).id, organization_ids=[ns.org],
                         environment="restore_copy", writer_freeze_reference="freeze:fixture")
    assert any(f["status"] == "fail" for f in raised.value.findings)
    assert counts(session, BillingMigrationOpening, CreditLot) == [0, 0]


def test_a_rehearsal_needs_explicit_targets_and_honours_the_pricing_unit(db, monkeypatch):
    w = world(db.session)
    with pytest.raises(br.RehearsalError, match="explicit"):
        br.run_rehearsal(db.session, run_key="r15-none", authorization_reference=AUTHORIZATION,
                         operator_user_id=w.operator, organization_ids=[], environment="fixtures")
    monkeypatch.setattr(br, "pricing_unit_findings", lambda session: [{"code": "pricing_rate_in_displayed_credits"}])
    with pytest.raises(br.RehearsalPreconditionError):
        rehearse(db.session, w)
    assert counts(db.session, BillingMigrationOpening) == [0]


# ---------------------------------------------------------------------------
# The rehearsal and its exact D16 reports
# ---------------------------------------------------------------------------

def test_a_fixture_rehearsal_runs_in_order_and_reports_every_d16_item(db):
    session = db.session
    w = world(session)
    out = rehearse(session, w)
    steps = [s["step"] for s in out["steps"]]
    # Run order: start, archive, establish every target, back fill, then map.
    assert steps[:2] == ["start_run", "archive_payments"]
    order = {name: [i for i, s in enumerate(steps) if s == name] for name in ("establish", "backfill", "map_plan")}
    assert max(order["establish"]) < min(order["backfill"]) and max(order["backfill"]) < min(order["map_plan"])
    assert len(order["establish"]) == len(order["backfill"]) == 5
    assert out["legacy_unchanged"]
    delta = out["census_delta"]
    assert delta["credit_lots"] == delta["credit_ledger_entries"] == delta["billing_migration_openings"] == 5
    assert (delta["financial_transactions"], delta["billing_subscriptions"], delta["entitlement_instances"]) == (0, 0, 0)
    assert delta["billing_migration_payment_archives"] == 2

    report = out["report"]
    outcome = {a["billing_account_id"]: a["outcome"] for a in report["accounts"]}
    assert outcome[w.free.account] == outcome[w.founder.account] == outcome[w.unverified.account] == "opened"
    assert outcome[w.negative.account] == "quarantined"
    assert report["sums"]["by_source"] == {"credit_pack_purchase": 5_500_000, "free_recurring": 210_000}
    assert report["sums"]["by_account"][w.founder.account]["opened_by_source"] == {
        "credit_pack_purchase": 2_500_000, "free_recurring": 50_000}
    assert report["sums"]["by_currency"]["usd"]["payments"] == 2
    assert report["sums"]["by_plan"]["free"]["accounts"] >= 4
    assert sum(p["lots"] for p in report["sums"]["by_period"].values()) == 5
    assert report["sums"]["by_period"]["non_expiring"] == {"lots": 2, "amount": 5_500_000}
    # Pre/post: every opened account conserves exactly; the lapsed pre-boundary cycle is expired, never opened.
    balances = {b["billing_account_id"]: b for b in report["balances"]["accounts"]}
    founder = balances[w.founder.account]
    assert founder["pre"]["accepted_recurring"] + founder["pre"]["accepted_persistent"] == \
        founder["post"]["available"] + founder["post"]["held"] == 2_550_000
    assert balances[w.expired.account]["pre"]["expired_recurring"] == 70_000
    assert balances[w.expired.account]["post"]["available"] == 0
    # Conflicts, duplicates, idempotency.
    negative = [c for c in report["unresolved_conflicts"] if c["billing_account_id"] == w.negative.account]
    assert {"negative_legacy_meter"} <= {c["code"] for c in negative}
    assert all(c["category"] != "other" for c in negative if not c["code"].startswith(("comparison:", "flag:")))
    dup = report["duplicates_and_idempotency"]
    assert dup["sources_opened_more_than_once"] == [] and dup["idempotency_claims_not_completed"] == []
    # Sampled proofs show input evidence and the exact target entries.
    proof = next(p for p in report["account_proofs"] if p["outcome"] == "opened")
    assert proof["input_evidence"]["sources"] and proof["target_entries"]
    assert all(e["entry_type"] == "migration_opening" and e["available_delta"] == e["opening_amount"]
               for e in proof["target_entries"])
    # Compatibility: every API field compared, recomputed equal to what each result stored.
    assert "users.credits_remaining" in report["compatibility"]["by_field"]
    assert report["compatibility"]["drift_from_stored_results"] == []
    assert report["historical_value_by_state"]["reconciles_to_phase14_population"]
    assert report["global_write_cutover_blocked"]  # no approved entitlement definitions, a quarantined account


def test_founder_test_credit_is_kept_identified_and_excluded_from_customer_reporting(db):
    session = db.session
    w = world(session)
    out = rehearse(session, w)
    separation = out["report"]["founder_test_separation"]
    lots = {lot["billing_account_id"]: lot for lot in separation["lots"]
            if lot["lot_source_type"] == "credit_pack_purchase"}
    founder, unverified = lots[w.founder.account], lots[w.unverified.account]
    # Kept exactly as opened: same lot type, original, opening, balance, non-expiring terms.
    assert (founder["funding"], founder["opening_amount"], founder["current_balance"]) == \
        ("founder_test", 2_500_000, 2_500_000)
    assert founder["attestation_references"] == [attest(w.founder.user)["reference"]]
    lot = session.get(CreditLot, founder["lot_id"])
    assert (lot.source_type, int(lot.original_amount), lot.expires_at) == ("credit_pack_purchase", 3_000_000, None)
    # Unverified stays unverified: neither test activity nor a genuine customer purchase.
    assert unverified["funding"] == "unverified"
    purchased = separation["purchased_credit"]
    assert purchased["genuine_customer"] == {"lots": 0, "opening_units": 0, "current_units": 0}
    assert purchased["excluded_founder_test"]["opening_units"] >= 2_500_000
    assert purchased["unverified"]["opening_units"] >= 3_000_000
    revenue = separation["customer_revenue"]
    assert revenue["verified_customer_cents_by_currency"] == {}
    assert revenue["excluded_founder_test_cents_by_currency"]["usd"] >= 1000
    assert revenue["unverified_not_revenue_cents_by_currency"]["usd"] >= 1000
    assert out["report"]["payment_archive"]["verified_customer_payments"] == 0
    assert separation["balances_and_classifications_changed"] is False
    archive = session.execute(sa.select(BillingMigrationPaymentArchive).where(
        BillingMigrationPaymentArchive.legacy_user_id == w.founder.user)).scalar_one()
    assert archive.classification == "test_activity"


def test_without_an_attestation_no_payment_is_classified_as_test_activity(db):
    w = world(db.session)
    out = rehearse(db.session, w, test_activity_attestation=None)
    funding = {lot["funding"] for lot in out["report"]["founder_test_separation"]["lots"]
               if lot["lot_source_type"] == "credit_pack_purchase"}
    assert funding == {"unverified"}
    assert out["report"]["founder_test_separation"]["purchased_credit"]["excluded_founder_test"]["lots"] == 0


def test_a_rerun_writes_nothing_and_reproduces_every_decision(db):
    session = db.session
    w = world(session)
    first = rehearse(session, w)
    second = rehearse(session, w)
    delta = second["census_delta"]
    assert delta["credit_lots"] == delta["credit_ledger_entries"] == delta["billing_migration_openings"] == 0
    assert delta["billing_migration_payment_archives"] == 0 and second["legacy_unchanged"]
    proof = br.rerun_proof(session, first_run_id=first["run_id"], second_run_id=second["run_id"])
    assert proof["zero_new_entries"] and proof["deterministic"], proof["differences"]
    assert (proof["new_openings"], proof["new_ledger_entries"], proof["new_payment_archives"]) == (0, 0, 0)
    second_outcomes = {a["billing_account_id"]: a["outcome"] for a in second["report"]["accounts"]}
    assert second_outcomes[w.free.account] == "unchanged" and second_outcomes[w.negative.account] == "quarantined"
    # The same call again resumes the latest run: every step replays.
    again = rehearse(session, w, key=second["report"]["run_key"])
    assert again["run_id"] == second["run_id"] and again["census_delta"]["credit_lots"] == 0
    assert {s["state"] for s in again["steps"] if s["step"] != "archive_payments"} == {"duplicate"}
    # A run superseded by a newer run fails closed before any step, writing nothing (C3).
    before = br.rehearsal_census(session)["counts"]
    with pytest.raises(br.RehearsalSupersededError):
        rehearse(session, w, key=first["report"]["run_key"])
    assert br.rehearsal_census(session)["counts"] == before
    assert second["report"]["duplicates_and_idempotency"]["cross_run_plan_mappings"] == []


@pytest.mark.parametrize("command, completed_before", [
    ("archive_legacy_payments", {"start_run"}),
    ("establish_billing_account", {"start_run", "archive_payments"}),
    ("backfill_billing_account", {"start_run", "archive_payments", "establish"}),
    ("map_legacy_plan", {"start_run", "archive_payments", "establish", "backfill"}),
])
def test_a_failure_at_any_step_keeps_earlier_steps_and_the_same_call_resumes(db, monkeypatch, command,
                                                                            completed_before):
    session = db.session
    w = world(session)
    original, calls = getattr(br, command), []

    def failing(*args, **kwargs):
        calls.append(kwargs)
        if len(calls) == 2 or command == "archive_legacy_payments":  # the second target, or the one archive
            raise RuntimeError("injected failure")
        return original(*args, **kwargs)

    monkeypatch.setattr(br, command, failing)
    key = f"r15-fail-{uuid.uuid4().hex[:6]}"
    with pytest.raises(br.RehearsalStepError) as raised:
        rehearse(session, w, key=key)
    step = {"establish_billing_account": "establish", "backfill_billing_account": "backfill",
            "map_legacy_plan": "map_plan"}.get(command)
    # Every earlier step, and the failing step's first target, stay committed.
    assert {s["step"] for s in raised.value.steps} == completed_before | ({step} if step else set())
    assert raised.value.step == (step or "archive_payments")
    assert not session.new and not session.dirty
    done = {s["subject"] for s in raised.value.steps if s["step"] == "backfill"}
    committed = session.execute(sa.select(BillingMigrationOpening.billing_account_id)).scalars().all()
    # Only completed backfills committed openings; the failed step left nothing behind.
    assert set(committed) <= done
    if command in ("archive_legacy_payments", "establish_billing_account"):
        assert committed == []
    monkeypatch.setattr(br, command, original)
    resumed = rehearse(session, w, key=key)
    clean = br.rehearsal_census(session)["counts"]
    assert clean["billing_migration_openings"] == clean["credit_lots"] == clean["credit_ledger_entries"] == 5
    assert resumed["report"]["sources_opened_more_than_once"] == []
    assert resumed["report"]["duplicates_and_idempotency"]["idempotency_claims_not_completed"] == []
    assert resumed["report"]["outcomes"] == {"opened": 3, "unchanged": 1, "quarantined": 1}


def test_a_transient_retry_is_retried_then_surfaces_as_a_step_failure(db, monkeypatch):
    session = db.session
    w = world(session)
    original, calls = br.backfill_billing_account, []

    def flaky(*args, **kwargs):
        calls.append(1)
        if len(calls) == 1:
            raise MigrationRetryError("concurrent")
        return original(*args, **kwargs)

    monkeypatch.setattr(br, "backfill_billing_account", flaky)
    out = rehearse(session, w)
    assert [s["attempts"] for s in out["steps"] if s["step"] == "backfill"][0] == 2
    monkeypatch.setattr(br, "backfill_billing_account",
                        lambda *a, **k: (_ for _ in ()).throw(MigrationRetryError("always")))
    with pytest.raises(br.RehearsalStepError):
        rehearse(session, w)


# ---------------------------------------------------------------------------
# F4: pre-2026-05-08 value, expired and live apart
# ---------------------------------------------------------------------------

def test_pre_boundary_value_is_reported_expired_live_and_undetermined_separately(db):
    session = db.session
    reset = UNIT_BOUNDARY_AT - timedelta(days=5)
    user(session, "lapsed", credits=70_000, reset=reset, prefs=meter(70_000, FREE, reset))
    holder = user(session, "pre-grant", credits=5000)
    grant(session, holder, 5000, 5000, granted_at=UNIT_BOUNDARY_AT - timedelta(days=30))
    user(session, "counter-only", credits=9000)
    session.flush()
    today = br.historical_value_by_state(session)
    meters = today["by_state"]["pre_unit_boundary_meter"]
    assert meters["expired"] == {"holders": 1, "amount": 70_000} and meters["live"]["holders"] == 0
    assert today["by_state"]["pre_unit_boundary_grant"]["live"] == {"holders": 1, "amount": 5000}
    assert today["by_state"]["legacy_meter_absent"]["undetermined"] == {"holders": 1, "amount": 9000}
    assert today["reconciles_to_phase14_population"]
    # The Phase 14 population counts the lapsed cycle as if live (F4); the split names it expired.
    assert historical_value_population(session)["pre_unit_boundary_meter"] == {"holders": 1, "amount": 70_000}
    during = br.historical_value_by_state(session, at=UNIT_BOUNDARY_AT + timedelta(days=10))
    assert during["by_state"]["pre_unit_boundary_meter"]["live"] == {"holders": 1, "amount": 70_000}


def test_reports_are_pure_reads(db):
    session = db.session
    w = world(session)
    out = rehearse(session, w)
    tables = sorted(flask_db.metadata.tables.values(), key=lambda t: t.name)
    before = [session.execute(sa.select(sa.func.count()).select_from(t)).scalar_one() for t in tables]
    br.rehearsal_report(session, run_id=out["run_id"])
    br.rehearsal_preconditions(session, environment="fixtures")
    br.rehearsal_census(session)
    br.founder_test_credit_separation(session)
    br.historical_value_by_state(session)
    br.rerun_proof(session, first_run_id=out["run_id"], second_run_id=out["run_id"])
    after = [session.execute(sa.select(sa.func.count()).select_from(t)).scalar_one() for t in tables]
    assert before == after and not session.new and not session.dirty


def test_phase15_rehearsal_has_no_live_callers():
    callers = sorted(str(p.relative_to(BACKEND)) for p in (BACKEND / "app").rglob("*.py")
                     # Phase 16 shadow comparison is inactive and read only.
                     if p.name not in ("billing_rehearsal.py", "billing_shadow.py") and "billing_rehearsal" in p.read_text())
    assert callers == []
    assert [p for p in (BACKEND / "scripts").rglob("*.py") if "billing_rehearsal" in p.read_text()] == []


# ---------------------------------------------------------------------------
# Audit C1: the runtime and the database decide, never the label
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("variables", [
    {"APP_ENV": "production"},
    {"APP_ENV": "prod"},
    {"APP_ENV": "", "ENV": "", "FLASK_ENV": "production"},
    {"APP_ENV": "test", "STRIPE_SECRET_KEY": "sk_live_fixture"},
])
def test_a_production_runtime_refuses_every_rehearsal_even_when_labelled_fixtures(db, monkeypatch, variables):
    session = db.session
    w = world(session)
    for name, value in variables.items():
        monkeypatch.setenv(name, value)
    before = br.rehearsal_census(session)["counts"]
    for environment in ("fixtures", "restore_copy"):
        with pytest.raises(br.RehearsalError, match="production runtime"):
            br.rehearsal_preconditions(session, environment=environment)
    with pytest.raises(br.RehearsalError, match="production runtime"):
        rehearse(session, w)
    session.rollback()
    assert br.rehearsal_census(session)["counts"] == before


@pytest.mark.parametrize("dialect, host, url_database, server_database, local", [
    ("sqlite", None, "/tmp/x.sqlite", None, True),
    ("postgresql", "127.0.0.1", "jaspen_phase15_test", "jaspen_phase15_test", True),
    ("postgresql", "localhost", "jaspen_test", "jaspen_test", True),
    ("postgresql", "db.example.com", "jaspen_test", "jaspen_test", False),  # remote host
    ("postgresql", "10.0.0.5", "jaspen_test", "jaspen_test", False),
    ("postgresql", "127.0.0.1", "jaspen", "jaspen", False),  # production-named database
    ("postgresql", "127.0.0.1", "jaspen_test", "jaspen", False),  # URL says test, the server disagrees
    ("postgresql", None, "jaspen_test", "jaspen_test", False),  # Unix socket: host unknown
    ("mysql", "127.0.0.1", "test", "test", False),
])
def test_only_a_verified_local_test_database_counts_as_fixtures(dialect, host, url_database, server_database, local):
    assert br.is_local_test_database(dialect=dialect, host=host, url_database=url_database,
                                     server_database=server_database) is local


def test_a_fixtures_label_cannot_switch_off_the_controls_on_an_unapproved_database(db, monkeypatch):
    session = db.session
    w = world(session)
    session.add(AIOperation(id=str(uuid.uuid4()), user_id=w.free.user, organization_id=w.free.org,
                            status="started", operation_type="conversation", router_version="test",
                            policy_version="test"))
    session.commit()
    monkeypatch.setattr(br, "is_local_test_database", lambda **facts: False)
    before = br.rehearsal_census(session)["counts"]
    with pytest.raises(br.RehearsalError, match="verified local test database"):
        br.rehearsal_preconditions(session, environment="fixtures")
    with pytest.raises(br.RehearsalError, match="verified local test database"):
        rehearse(session, w)
    # The same database as a restore copy keeps every control: in-flight work, writer freeze, roles.
    restore = br.rehearsal_preconditions(session, environment="restore_copy")
    assert not restore["ready"]
    assert finding(restore, "no_in_flight_ai_operations")["status"] == "fail"
    assert finding(restore, "legacy_writers_frozen_before_snapshot")["status"] == "fail"
    session.rollback()
    assert br.rehearsal_census(session)["counts"] == before


def test_preconditions_record_the_authoritative_environment(db):
    facts = finding(br.rehearsal_preconditions(db.session, environment="fixtures"),
                    "runtime_and_database_environment")["detail"]
    assert facts["production_runtime"] is False and facts["local_test_database"] is True


# ---------------------------------------------------------------------------
# Audit C2: team pools funded by founder tests
# ---------------------------------------------------------------------------

def team_pool(session, *, invoices=1):
    """A team organization whose pool meter is paid by its owner's subscription invoices (committed)."""
    reset = now(session) - timedelta(days=2)
    owner = user(session, "pool-owner", plan="team", credits=1_000_000, customer=f"cus_{uuid.uuid4().hex[:10]}")
    member = user(session, "pool-member", plan="team", credits=1_000_000)
    ns = organization(session, owner, members=(member,), settings=meter(1_000_000, TEAM, reset),
                      customer=owner.stripe_customer_id)
    owner.subscription_status, owner.stripe_subscription_id = "active", f"sub_{uuid.uuid4().hex[:10]}"
    for _ in range(invoices):
        add_invoice(session, owner)
    ns.owner, ns.member = owner.id, member.id
    session.commit()
    return ns


def add_invoice(session, owner):
    row = payment(session, owner, source="subscription_invoice", paid=3900)
    row.plan_key, row.billing_interval, row.stripe_subscription_id = "team", "month", owner.stripe_subscription_id
    session.flush()
    return row


def pool_rehearsal(session, ns, attestation):
    staff = operator(session).id
    session.commit()
    return br.run_rehearsal(session, run_key=f"r15-pool-{uuid.uuid4().hex[:8]}", authorization_reference=AUTHORIZATION,
                            operator_user_id=staff, organization_ids=[ns.org], environment="fixtures",
                            test_activity_attestation=attestation)


def pool_lot(out, ns):
    (lot,) = [lot for lot in out["report"]["founder_test_separation"]["lots"]
              if lot["billing_account_id"] == ns.account and lot["legacy_source_kind"] == "organization_recurring_meter"]
    return lot


def test_a_fully_attested_team_pool_is_founder_test_and_kept_exactly_as_opened(db):
    session = db.session
    ns = team_pool(session, invoices=2)
    out = pool_rehearsal(session, ns, attest(ns.owner))
    lot = pool_lot(out, ns)
    assert (lot["funding"], lot["funding_basis"]) == ("founder_test", "every_payer_invoice_attested_test_activity")
    assert len(lot["payment_ids"]) == 2 and lot["attestation_references"] == [attest(ns.owner)["reference"]]
    assert (lot["opening_amount"], lot["current_balance"]) == (1_000_000, 1_000_000)
    row = session.get(CreditLot, lot["lot_id"])
    # Balance, original terms, and attribution untouched: an unattributed pool lot to its legacy cycle end.
    assert (row.source_type, row.member_attribution_id, int(row.original_amount)) == \
        ("subscription_recurring", None, TEAM)
    assert row.expires_at is not None
    purchased = out["report"]["founder_test_separation"]["purchased_credit"]
    assert purchased["excluded_founder_test"]["opening_units"] == 1_000_000
    assert purchased["unverified"]["opening_units"] == 0
    assert purchased["genuine_customer"]["opening_units"] == 0


def test_an_unattested_team_pool_stays_unverified(db):
    session = db.session
    ns = team_pool(session)
    out = pool_rehearsal(session, ns, None)
    lot = pool_lot(out, ns)
    assert (lot["funding"], lot["funding_basis"]) == ("unverified", "invoices_not_all_attested_test_activity")
    purchased = out["report"]["founder_test_separation"]["purchased_credit"]
    assert purchased["unverified"]["opening_units"] == 1_000_000
    assert purchased["excluded_founder_test"]["lots"] == 0


def test_a_mixed_team_pool_stays_unverified_and_the_archive_conflict_is_reported(db):
    session = db.session
    ns = team_pool(session)
    staff = operator(session)
    archive(session, run(session, operator_id=staff.id))  # the first invoice archived without an attestation
    owner = session.get(User, ns.owner)
    add_invoice(session, owner)
    session.commit()
    out = pool_rehearsal(session, ns, attest(ns.owner))
    lot = pool_lot(out, ns)
    assert (lot["funding"], lot["funding_basis"]) == ("unverified", "invoices_not_all_attested_test_activity")
    assert out["report"]["founder_test_separation"]["purchased_credit"]["excluded_founder_test"]["lots"] == 0
    codes = {c["code"] for c in out["report"]["unresolved_conflicts"] if c["stage"].startswith("payment_archive")}
    assert "classification_differs_from_archive" in codes


# ---------------------------------------------------------------------------
# Audit C3: an interrupted older run never resumes over a newer run's records
# ---------------------------------------------------------------------------

def test_an_interrupted_older_run_cannot_resume_after_a_newer_run_and_writes_no_mappings(db, monkeypatch):
    session = db.session
    w = world(session)
    original = br.map_legacy_plan
    monkeypatch.setattr(br, "map_legacy_plan", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("interrupted")))
    older_key = f"r15-older-{uuid.uuid4().hex[:6]}"
    with pytest.raises(br.RehearsalStepError) as raised:
        rehearse(session, w, key=older_key)
    assert raised.value.step == "map_plan"
    monkeypatch.setattr(br, "map_legacy_plan", original)
    newer = rehearse(session, w)
    assert newer["report"]["plan_mapping_outcomes"]["mapped"] + \
        newer["report"]["plan_mapping_outcomes"]["quarantined"] + \
        newer["report"]["plan_mapping_outcomes"]["mapped_pending_processor"] == 5
    before = br.rehearsal_census(session)["counts"]
    with pytest.raises(br.RehearsalSupersededError, match="newer run"):
        rehearse(session, w, key=older_key)
    assert br.rehearsal_census(session)["counts"] == before  # no mapping, no registry row, nothing
    older = session.execute(sa.select(br.BillingMigrationRun).where(
        br.BillingMigrationRun.run_key == older_key)).scalar_one()
    assert session.execute(sa.select(sa.func.count()).select_from(BillingMigrationPlanMapping).where(
        BillingMigrationPlanMapping.run_id == older.id)).scalar_one() == 0
    # Defence in depth: with the up-front check bypassed, each step still refuses another run's establishment.
    monkeypatch.setattr(br, "_newer_runs_holding_targets", lambda *a: [])
    with pytest.raises(br.RehearsalStepError) as step:
        rehearse(session, w, key=older_key)
    assert step.value.step == "backfill" and isinstance(step.value.__cause__, br.RehearsalSupersededError)
    assert br.rehearsal_census(session)["counts"] == before


# ---------------------------------------------------------------------------
# Audit C4: every archive conflict reaches the final report
# ---------------------------------------------------------------------------

def test_attestation_conflicts_and_attested_payers_without_payments_appear_in_the_report(db):
    session = db.session
    w = world(session)
    rehearse(session, w, test_activity_attestation=None)  # archives every payment unverified
    bystander = user(session, "attested-no-payments")
    session.commit()
    out = rehearse(session, w, test_activity_attestation=attest(w.founder.user, w.unverified.user, bystander.id))
    step = next(s for s in out["steps"] if s["step"] == "archive_payments")["findings"]
    reported = {(c["code"], c["subject"]) for c in out["report"]["unresolved_conflicts"]
                if c["stage"].startswith("payment_archive")}
    assert {(f["code"], f["subject"]) for f in step} <= reported
    founder_payment = session.execute(sa.select(BillingMigrationPaymentArchive.payment_id).where(
        BillingMigrationPaymentArchive.legacy_user_id == w.founder.user)).scalar_one()
    assert ("classification_differs_from_archive", founder_payment) in reported
    assert ("attested_payer_without_payments", bystander.id) in reported
    assert out["report"]["unresolved_by_category"]["payment"] >= 3
    # The archive is permanent: the later attestation is reported, never applied.
    assert session.execute(sa.select(BillingMigrationPaymentArchive.classification).where(
        BillingMigrationPaymentArchive.payment_id == founder_payment)).scalar_one() == "unverified"


# ---------------------------------------------------------------------------
# Downgrade and rollback (D16 "Rollback"): SQLite
# ---------------------------------------------------------------------------

def _sqlite_schema(engine):
    with engine.connect() as connection:
        return sorted(tuple(r) for r in connection.execute(sa.text(
            "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")))


def test_sqlite_empty_round_trip_is_exact_and_downgrade_refuses_once_a_run_exists(tmp_path):
    module = _revision()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase15.sqlite'}")
    try:
        flask_db.metadata.create_all(engine, tables=[t for t in flask_db.metadata.sorted_tables
                                                     if t.name not in PHASE14_TABLES])
        table, _name, old, new = module.PERMISSION_CHECK
        with _ops(engine) as connection:
            module._phase11()._sqlite_replace_check(table, new, old)
            for statement in _earlier_sqlite_lot_triggers().values():
                connection.execute(sa.text(statement))
        parent = _sqlite_schema(engine)
        with _ops(engine):
            module.upgrade()
        head = _sqlite_schema(engine)
        with _ops(engine):
            module.downgrade()
        assert _sqlite_schema(engine) == parent  # empty downgrade restores the parent exactly
        with _ops(engine):
            module.upgrade()
        assert _sqlite_schema(engine) == head
        with Session(engine) as session:
            staff = User(id=f"p15-op-{uuid.uuid4().hex[:6]}", email=f"{uuid.uuid4().hex[:8]}@example.test",
                         name="op", password_hash="x")
            session.add(staff)
            session.flush()
            br.start_migration_run(session, run_key="r15", authorization_reference=AUTHORIZATION,
                                   actor_type="system", actor_id="phase15-test", operator_user_id=staff.id)
            session.commit()
        with pytest.raises(module.Phase14EvidenceNotEmptyError):
            with _ops(engine):
                module.downgrade()
        assert _sqlite_schema(engine) == head  # refused atomically; evidence and schema intact
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# PostgreSQL 18.6, every Phase 3-14 guard live
# ---------------------------------------------------------------------------

def _pg_world(engine):
    with migrated(engine) as session:
        return world(session)


@PG
def test_postgres_rehearsal_with_every_guard_live_reruns_to_zero_and_keeps_legacy_unchanged():
    engine = _migrated_engine()
    try:
        w = _pg_world(engine)
        with migrated(engine) as session:
            first = rehearse(session, w)
            second = rehearse(session, w)
            assert first["legacy_unchanged"] and second["legacy_unchanged"]
            assert first["census_delta"]["billing_migration_openings"] == 5
            assert second["census_delta"]["billing_migration_openings"] == 0
            assert second["census_delta"]["credit_ledger_entries"] == 0
            proof = br.rerun_proof(session, first_run_id=first["run_id"], second_run_id=second["run_id"])
            mine = [d for d in proof["differences"]
                    if d.get("billing_account_id") in w.accounts or d.get("organization_id") in w.orgs]
            assert proof["zero_new_entries"] and mine == []
            separation = first["report"]["founder_test_separation"]
            funding = {lot["billing_account_id"]: lot["funding"] for lot in separation["lots"]
                       if lot["lot_source_type"] == "credit_pack_purchase" and lot["billing_account_id"] in w.accounts}
            assert funding == {w.founder.account: "founder_test", w.unverified.account: "unverified"}
            assert first["report"]["compatibility"]["drift_from_stored_results"] == []
            assert first["report"]["sources_opened_more_than_once"] == []
    finally:
        engine.dispose()


@PG
def test_postgres_fixtures_are_refused_on_a_local_database_not_named_for_tests():
    """The maintenance database on the same server: loopback, but not a test database (C1)."""
    url = sa.engine.make_url(os.environ["TEST_DATABASE_URL"]).set(database="postgres")
    engine = sa.create_engine(url)
    try:
        with migrated(engine) as session:
            with pytest.raises(br.RehearsalError, match="verified local test database"):
                br.rehearsal_preconditions(session, environment="fixtures")
            facts = br.database_environment(session)
            assert (facts["server_database"], facts["local_test_database"]) == ("postgres", False)
    finally:
        engine.dispose()


@PG
def test_postgres_concurrent_rehearsals_open_each_source_exactly_once():
    engine = _migrated_engine()
    try:
        w = _pg_world(engine)

        def one(_):
            with migrated(engine) as session:
                try:
                    return rehearse(session, w)
                except (br.RehearsalSupersededError, br.RehearsalStepError) as exc:
                    return exc  # an interleaved run fails closed rather than build on the other run (C3)

        with ThreadPoolExecutor(max_workers=2) as pool:
            outs = list(pool.map(one, range(2)))
        assert any(isinstance(o, dict) for o in outs)
        with migrated(engine) as session:
            rows = session.execute(sa.select(BillingMigrationOpening.legacy_source_id, sa.func.count())
                                   .where(BillingMigrationOpening.billing_account_id.in_(sorted(w.accounts)))
                                   .group_by(BillingMigrationOpening.legacy_source_id)).all()
            assert len(rows) == 5 and all(count == 1 for _source, count in rows)
            mappings = session.execute(sa.select(BillingMigrationPlanMapping).where(
                BillingMigrationPlanMapping.billing_account_id.in_(sorted(w.accounts)))).scalars().all()
            assert mappings and all(session.get(BillingMigrationEstablishment, m.establishment_id).run_id == m.run_id
                                    for m in mappings)
    finally:
        engine.dispose()


@PG
def test_postgres_r1_a_run_cannot_commit_a_mapping_to_an_establishment_a_concurrent_run_wrote(monkeypatch):
    """Re-acceptance R1, forced deterministically with two sessions.

    Run A passes its ownership check for its first mapping. Before A's
    Phase 14 mapping lookup, run B (its own session and connection) commits a
    full rehearsal that re-establishes the same organizations. A's mapping
    must not commit; B's records stay intact; nothing is duplicated.
    """
    engine = _migrated_engine()
    try:
        w = _pg_world(engine)
        original = br.map_legacy_plan
        seen = {}

        def interleaved(session, *, run_id, billing_account_id):
            if "b" not in seen:
                organization_id = session.execute(sa.select(BillingMigrationEstablishment.organization_id).where(
                    BillingMigrationEstablishment.billing_account_id == billing_account_id,
                    BillingMigrationEstablishment.run_id == run_id)).scalar_one()
                # A's ownership check has just passed: the latest establishment is A's.
                seen["a_owned"] = br._owned_establishment(session, run_id, organization_id).run_id == run_id
                seen["b"] = True
                with migrated(engine) as other:
                    monkeypatch.setattr(br, "map_legacy_plan", original)
                    seen["b_out"] = rehearse(other, w, key=f"r15-b-{uuid.uuid4().hex[:6]}")
                    monkeypatch.setattr(br, "map_legacy_plan", interleaved)
                    latest = other.execute(sa.select(BillingMigrationEstablishment).where(
                        BillingMigrationEstablishment.organization_id == organization_id)
                        .order_by(BillingMigrationEstablishment.created_at.desc(),
                                  BillingMigrationEstablishment.id.desc()).limit(1)).scalar_one()
                    seen["b_holds_latest"] = latest.run_id == seen["b_out"]["run_id"]
                    seen["census_after_b"] = br.rehearsal_census(other)["counts"]
                    other.rollback()
                seen["a_account"] = billing_account_id
            return original(session, run_id=run_id, billing_account_id=billing_account_id)

        monkeypatch.setattr(br, "map_legacy_plan", interleaved)
        a_key = f"r15-a-{uuid.uuid4().hex[:6]}"
        with migrated(engine) as session:
            with pytest.raises(br.RehearsalStepError) as raised:
                rehearse(session, w, key=a_key)
        monkeypatch.setattr(br, "map_legacy_plan", original)
        assert seen["a_owned"] and seen["b_holds_latest"]
        assert raised.value.step == "map_plan" and raised.value.subject == seen["a_account"]
        assert isinstance(raised.value.__cause__, br.RehearsalSupersededError)
        b = seen["b_out"]
        with migrated(engine) as session:
            a_run = session.execute(sa.select(br.BillingMigrationRun).where(
                br.BillingMigrationRun.run_key == a_key)).scalar_one()
            assert br.rehearsal_census(session)["counts"] == seen["census_after_b"]  # A's failed step left nothing
            assert session.execute(sa.select(sa.func.count()).select_from(BillingMigrationPlanMapping).where(
                BillingMigrationPlanMapping.run_id == a_run.id)).scalar_one() == 0
            mappings = session.execute(sa.select(BillingMigrationPlanMapping).where(
                BillingMigrationPlanMapping.billing_account_id.in_(sorted(w.accounts)))).scalars().all()
            assert len(mappings) == 5 and {m.run_id for m in mappings} == {b["run_id"]}
            assert all(session.get(BillingMigrationEstablishment, m.establishment_id).run_id == m.run_id
                       for m in mappings)  # zero cross-run mappings
            assert br.rehearsal_report(session, run_id=a_run.id)["duplicates_and_idempotency"][
                "cross_run_plan_mappings"] == []
            report_b = br.rehearsal_report(session, run_id=b["run_id"])
            assert report_b["duplicates_and_idempotency"]["cross_run_plan_mappings"] == []
            assert report_b["sources_opened_more_than_once"] == []
            assert b["census_delta"]["billing_migration_openings"] == 0  # A had already opened every source
            assert b["census_delta"]["credit_ledger_entries"] == 0 and b["census_delta"]["credit_lots"] == 0
            rows = session.execute(sa.select(BillingMigrationOpening.legacy_source_id, sa.func.count())
                                   .where(BillingMigrationOpening.billing_account_id.in_(sorted(w.accounts)))
                                   .group_by(BillingMigrationOpening.legacy_source_id)).all()
            assert len(rows) == 5 and all(count == 1 for _source, count in rows)
            archives = session.execute(sa.select(BillingMigrationPaymentArchive.payment_id, sa.func.count())
                                       .group_by(BillingMigrationPaymentArchive.payment_id)).all()
            assert all(count == 1 for _payment, count in archives)
    finally:
        engine.dispose()


@PG
def test_postgres_restore_copy_needs_a_least_privilege_migration_role_and_a_read_only_runtime_role():
    """Disposable NOLOGIN roles in the test container only; dropped afterwards."""
    engine = _migrated_engine()
    suffix = uuid.uuid4().hex[:8]
    migration_role, runtime_role = f"p15_test_mig_{suffix}", f"p15_test_rt_{suffix}"
    try:
        with engine.begin() as connection:
            connection.execute(sa.text(f"CREATE ROLE {migration_role} NOLOGIN"))
            connection.execute(sa.text(f"CREATE ROLE {runtime_role} NOLOGIN"))
            connection.execute(sa.text(f"GRANT SELECT ON ALL TABLES IN SCHEMA public TO {migration_role}"))
            connection.execute(sa.text(f"GRANT INSERT ON {', '.join(PHASE14_TABLES)} TO {migration_role}"))
            connection.execute(sa.text(f"GRANT {migration_role}, {runtime_role} TO current_user"))
        with migrated(engine) as session:
            superuser = br.rehearsal_preconditions(session, environment="restore_copy", runtime_role=runtime_role,
                                                   writer_freeze_reference="freeze:fixture")
            assert finding(superuser, "migration_role_least_privilege")["detail"]["superuser"] is True
            session.execute(sa.text(f"SET LOCAL ROLE {migration_role}"))
            least = br.rehearsal_preconditions(session, environment="restore_copy", runtime_role=runtime_role,
                                               writer_freeze_reference="freeze:fixture")
            assert finding(least, "migration_role_least_privilege")["status"] == "pass"
            assert finding(least, "runtime_role_cannot_write_phase14")["status"] == "pass"
            assert finding(least, "legacy_writers_frozen_before_snapshot")["status"] == "pass"
            session.rollback()
        with engine.begin() as connection:
            connection.execute(sa.text(f"GRANT INSERT ON billing_migration_openings TO {runtime_role}"))
            connection.execute(sa.text(f"GRANT UPDATE ON billing_migration_runs TO {migration_role}"))
        with migrated(engine) as session:
            session.execute(sa.text(f"SET LOCAL ROLE {migration_role}"))
            broad = br.rehearsal_preconditions(session, environment="restore_copy", runtime_role=runtime_role,
                                               writer_freeze_reference="freeze:fixture")
            assert not broad["ready"]
            assert finding(broad, "migration_role_least_privilege")["detail"]["update_delete_or_truncate"] == [
                "billing_migration_runs"]
            assert finding(broad, "runtime_role_cannot_write_phase14")["detail"]["insert_on"] == [
                "billing_migration_openings"]
            session.rollback()
    finally:
        with engine.begin() as connection:
            for role in (migration_role, runtime_role):
                connection.execute(sa.text(f"DROP OWNED BY {role}"))
                connection.execute(sa.text(f"DROP ROLE {role}"))
        engine.dispose()


def _pg_signature(engine):
    with engine.connect() as connection:
        return {
            "columns": connection.execute(sa.text(
                "SELECT table_name, column_name, data_type, is_nullable, column_default FROM "
                "information_schema.columns WHERE table_schema='public' ORDER BY 1, 2")).all(),
            "constraints": connection.execute(sa.text(
                "SELECT conrelid::regclass::text, conname, pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE connamespace='public'::regnamespace ORDER BY 1, 2")).all(),
            "functions": connection.execute(sa.text(
                "SELECT proname, prosrc FROM pg_proc WHERE pronamespace='public'::regnamespace ORDER BY 1")).all(),
            "triggers": connection.execute(sa.text(
                "SELECT tgrelid::regclass::text, tgname, pg_get_triggerdef(oid) FROM pg_trigger "
                "WHERE NOT tgisinternal ORDER BY 1, 2")).all(),
            "indexes": connection.execute(sa.text(
                "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname='public' ORDER BY 1")).all(),
        }


@PG
def test_postgres_empty_round_trip_is_exact_and_downgrade_refuses_after_a_rehearsal():
    """On a separate fresh database at the Phase 14 head (TEST_PHASE15_ROUNDTRIP_DATABASE_URL)."""
    url = os.environ.get("TEST_PHASE15_ROUNDTRIP_DATABASE_URL")
    if not url:
        pytest.skip("TEST_PHASE15_ROUNDTRIP_DATABASE_URL is not configured")
    module = _revision()
    engine = sa.create_engine(url)
    try:
        with engine.connect() as connection:
            if any(connection.execute(sa.text(f"SELECT 1 FROM {t} LIMIT 1")).first() for t in PHASE14_TABLES):
                pytest.skip("the round-trip database must be freshly migrated and empty")
        head = _pg_signature(engine)
        with _ops(engine):
            module.downgrade()
        parent = _pg_signature(engine)
        assert not any(t in {row[0] for row in parent["columns"]} for t in PHASE14_TABLES)
        with _ops(engine):
            module.upgrade()
        assert _pg_signature(engine) == head
        w = _pg_world(engine)
        with migrated(engine) as session:
            out = rehearse(session, w)
            assert out["census_delta"]["billing_migration_openings"] == 5
        with pytest.raises(module.Phase14EvidenceNotEmptyError):
            with _ops(engine):
                module.downgrade()
        assert _pg_signature(engine) == head
        with migrated(engine) as session:
            again = rehearse(session, w)
            assert again["census_delta"]["credit_ledger_entries"] == 0 and again["legacy_unchanged"]
            lots = session.execute(sa.select(sa.func.count()).select_from(CreditLedgerEntry).where(
                CreditLedgerEntry.billing_account_id.in_(sorted(w.accounts)))).scalar_one()
            assert lots == 5
    finally:
        engine.dispose()
