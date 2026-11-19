"""Inactive Phase 15 local rehearsal of the Phase 14 legacy backfill (D16 reports, D18 row 15).

Phase 15 orchestrates the accepted Phase 14 commands on local fixtures or an
approved restore copy and proves the result with exact reports. It adds no
table, no migration, and no command that writes anything Phase 14 does not
already write; every report here is a pure read.

* **Preconditions** (``rehearsal_preconditions``). Only two environments
  exist: ``fixtures`` (local test data) and ``restore_copy`` (an approved,
  restored, non-production copy). The label is never trusted on its own: a
  production runtime (``rate_limits.is_production_runtime``) refuses every
  rehearsal, and ``fixtures`` runs only on a verified local test database
  (SQLite, or PostgreSQL on a loopback host whose configured and
  server-reported names contain ``test``). Gate 1 units and the 3,600,000-per-provider-dollar pricing unit
  must hold. A restore copy additionally needs PostgreSQL, an attested
  writer freeze taken before the snapshot (every D04 writer, including the
  unified line's ``TurnBilling``), no in-flight AI operation, a connected
  migration-only role (INSERT on the Phase 14 tables, no UPDATE, DELETE,
  TRUNCATE, or superuser), and a named runtime role with no INSERT on any
  Phase 14 table. Fixture runs need none of those cutover controls; the
  findings say which checks are local and which are restore-copy or cutover
  only.
* **Run order** (``run_rehearsal``): start the run, archive every legacy
  payment, establish every explicit organization, back fill every
  established account, then map every established account's plan. Each step
  commits on its own, so a failure leaves every earlier step intact and
  nothing of the failed step; repeating the same call resumes the same run
  (every Phase 14 command replays to ``duplicate`` or ``unchanged``). A
  transient ``MigrationRetryError`` is retried a bounded number of times.
* **Reports** (``rehearsal_report``): the Phase 14 run report plus the D16
  reconciliation report items: sums by billing account, source, currency,
  plan, and period; pre and post available, held, settled, expired, and
  reversed totals; every duplicate reference and idempotency conflict; every
  unresolved owner, source, expiry, contract, and payment conflict; sampled
  account proofs (input evidence and target entries); the compatibility
  comparison of every API field, recomputed and checked against the stored
  result; pre-2026-05-08 value split into expired, live, and undetermined
  (re-acceptance F4); and the founder-test separation.
* **Founder-test separation** (founder decision 2026-11-19,
  ``founder_test_credit_separation``). Jaspen has no paying customers.
  Credits funded by a payment archived ``test_activity`` stay exactly as
  opened (same lot type, amounts, and terms) and are reported as founder
  test activity, excluded from customer revenue and from genuine purchased
  credit. Unverified payments stay unverified: never counted as test and
  never as genuine customer purchases. No balance, lot, or classification
  is changed by any report.
* **Rerun proof** (``rerun_proof``): a second run over the same evidence
  writes zero openings, lots, ledger entries, and archives, and reproduces
  every evidence fingerprint.

Nothing in live routes, the AI runtime, webhooks, jobs, scripts, or startup
calls this module.
"""

from collections import Counter, defaultdict
import hashlib
import json

from sqlalchemy import func, select, text

from . import db
from .billing_entitlements import add_calendar_months
from .billing_migration import (
    ARCHIVE_NAMESPACE,
    ESTABLISHMENT_NAMESPACE,
    OPENING_NAMESPACE,
    PLAN_MAPPING_NAMESPACE,
    RESULT_NAMESPACE,
    REVIEW_NAMESPACE,
    RUN_NAMESPACE,
    UNIT_BOUNDARY_AT,
    MigrationError,
    _database_clock,
    MigrationRetryError,
    MigrationUnitError,
    archive_legacy_payments,
    backfill_billing_account,
    establish_billing_account,
    historical_value_population,
    map_legacy_plan,
    migration_run_report,
    plan_payment_archive,
    pricing_unit_findings,
    start_migration_run,
    verify_credit_unit_equivalence,
)
from .billing_projections import _credit_view, _int_or_none, _lot_balances, _meter, _parsed, _utc, \
    compare_legacy_compatibility
from .rate_limits import is_production_runtime
from .models import (
    AIOperation,
    CreditLedgerEntry,
    Organization,
    PersistentCreditGrant,
    User,
)
from .billing_config import SHARED_POOL_PLANS
from .models_billing_phase14 import (
    REVIEW_PERMISSION,
    BillingMigrationPayerBinding,
    BillingMigrationPaymentAttribution,
    BillingMigrationAccountResult,
    BillingMigrationEstablishment,
    BillingMigrationOpening,
    BillingMigrationPaymentArchive,
    BillingMigrationPlanMapping,
    BillingMigrationRun,
)


REHEARSAL_VERSION = "jaspen.billing.rehearsal.v1"
ENVIRONMENTS = ("fixtures", "restore_copy")
# Founder decision 2026-11-19: confirmed founder-test payments and their credits are kept, identifiable,
# and excluded from customer revenue and genuine purchased-credit reporting; balances never change.
FOUNDER_TEST_POLICY = "founder-decision:2026-11-19:founder-test-credits-kept-and-excluded-from-customer-reporting"

PHASE14_TABLES = (
    "billing_migration_runs", "billing_migration_establishments", "billing_migration_payer_bindings",
    "billing_migration_payment_attributions", "billing_migration_account_results", "billing_migration_reviews",
    "billing_migration_openings", "billing_migration_payment_archives", "billing_migration_plan_mappings",
)
# Target and downstream tables a rehearsal may write (Phase 3) or must never write (Phases 4, 5.2).
CENSUS_TABLES = PHASE14_TABLES + (
    "billing_accounts", "credit_lots", "credit_ledger_entries", "idempotency_registry",
    "financial_transactions", "billing_subscriptions", "entitlement_instances",
)
MIGRATION_NAMESPACES = (RUN_NAMESPACE, ESTABLISHMENT_NAMESPACE, RESULT_NAMESPACE, OPENING_NAMESPACE,
                        REVIEW_NAMESPACE, ARCHIVE_NAMESPACE, PLAN_MAPPING_NAMESPACE)
PURCHASED_LOT_SOURCES = ("credit_pack_purchase", "subscription_recurring")
RETRY_ATTEMPTS = 3

# Quarantine codes grouped for the D16 "every unresolved owner/source/expiry/contract/invoice-line" list.
CONFLICT_CATEGORIES = {
    "owner": {"ambiguous_owner", "plan_owner_unresolved", "payer_binding_conflict", "attributed_member_not_active",
              "organization_owner_missing", "organization_plan_paid_elsewhere", "payment_owner_conflict",
              "grant_organization_conflict", "billing_account_not_established", "establishment_quarantined",
              "establishment_evidence_changed", "evidence_changed_since_establishment"},
    "source": {"legacy_source_opened_elsewhere", "duplicate_external_reference", "unknown_grant_source",
               "malformed_persistent_grant", "contradictory_grant_status", "persistent_grant_log_incomplete",
               "persistent_grant_log_mismatch", "persistent_grant_transaction_sum_mismatch",
               "legacy_meter_absent", "malformed_legacy_meter", "negative_legacy_meter", "meter_above_cycle_limit",
               "overage_in_recurring_meter", "null_legacy_balance", "evidence_changed_since_opening",
               "counter_below_proven_purchased", "counter_above_evidence", "reset_date_conflict",
               "reset_date_in_future", "grant_in_future"},
    "expiry": {"expiry_terms_unestablished", "pre_unit_boundary_value", "grant_date_missing"},
    "contract": {"enterprise_without_contract", "enterprise_pool_meter_value", "unknown_legacy_plan",
                 "unknown_legacy_entitlement", "plan_without_subscription_evidence", "subscription_state_conflict",
                 "subscription_status_missing", "subscription_status_unrecognized",
                 "subscription_history_without_end_state", "billing_account_closed"},
    "payment": {"payment_evidence_missing", "payment_not_attributed_to_account", "payment_source_conflict",
                "payment_amount_conflict", "payment_not_archived", "archived_payment_changed",
                "archived_payment_missing", "legacy_dispute_state_unknown", "classification_differs_from_archive",
                "attested_payer_without_payments"},
    "operation": {"legacy_operation_in_flight"},
}


class RehearsalError(MigrationError):
    """A rehearsal that cannot run as asked (environment, preconditions)."""


class RehearsalPreconditionError(RehearsalError):
    """A rehearsal precondition failed; ``findings`` lists every check."""

    def __init__(self, message, findings):
        super().__init__(message)
        self.findings = findings


class RehearsalSupersededError(RehearsalError):
    """A run cannot resume over records a newer run made for the same targets (audit C3)."""


class RehearsalStepError(RehearsalError):
    """A rehearsal step failed; every earlier step is committed and ``steps`` lists them."""

    def __init__(self, step, subject, steps):
        super().__init__(f"rehearsal step {step} failed for {subject}; earlier steps are committed")
        self.step, self.subject, self.steps = step, subject, steps


def _fingerprint(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _category(code):
    base = code.split(":", 1)[0]
    if base in ("comparison", "flag"):
        return "compatibility"
    return next((name for name, codes in CONFLICT_CATEGORIES.items() if code in codes), "other")


# ---------------------------------------------------------------------------
# Census and the legacy fingerprint (pure)
# ---------------------------------------------------------------------------

def _count(session, table_name):
    table = db.metadata.tables[table_name]
    return int(session.execute(select(func.count()).select_from(table)).scalar_one())


def legacy_fingerprint(session):
    """A digest of every legacy field the backfill reads (pure); a rehearsal must leave it unchanged."""
    tables = {
        "users": ("id", "credits_remaining", "credits_reset_at", "ui_preferences", "subscription_plan",
                  "subscription_status", "stripe_customer_id", "stripe_subscription_id", "seat_limit", "max_seats"),
        "organizations": ("id", "owner_user_id", "plan_key", "settings"),
        "organization_members": ("organization_id", "user_id", "role", "status"),
        "persistent_credit_grants": ("id", "user_id", "organization_id", "source", "status", "original_amount",
                                     "remaining_amount", "external_reference", "granted_at"),
        "persistent_credit_transactions": ("id", "grant_id", "transaction_type", "amount", "balance_after"),
        "payments": ("id", "external_reference", "source", "user_id", "organization_id", "billing_account_id",
                     "currency", "amount_paid_cents", "amount_due_cents", "discount_cents", "is_comped",
                     "plan_key", "billing_interval", "stripe_subscription_id", "paid_at"),
        "account_entitlements": ("id", "user_id", "organization_id", "entitlement_key", "revoked_at"),
        "ai_operations": ("id", "user_id", "status", "charged_credits"),
    }
    digest = {}
    for name, columns in tables.items():
        table = db.metadata.tables[name]
        rows = session.execute(select(*[table.c[c] for c in columns])
                               .order_by(*[table.c[c] for c in columns[:2]])).all()
        digest[name] = _fingerprint([list(row) for row in rows])
    return {"tables": digest, "fingerprint": _fingerprint(digest)}


def rehearsal_census(session):
    """Row counts of every table a rehearsal may or must not write, and the legacy fingerprint (pure)."""
    with session.no_autoflush:
        return {"counts": {name: _count(session, name) for name in CENSUS_TABLES},
                "legacy": legacy_fingerprint(session)}


def _delta(before, after):
    return {name: after["counts"][name] - before["counts"][name] for name in CENSUS_TABLES}


# ---------------------------------------------------------------------------
# Environment protection (audit C1): the runtime and the database decide, never a label
# ---------------------------------------------------------------------------

# The hosts the test configuration accepts for a disposable PostgreSQL (tests/conftest.py).
LOCAL_TEST_DATABASE_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "postgres"})


def is_local_test_database(*, dialect, host, url_database, server_database):
    """Whether the connected database is a disposable local test database (pure).

    SQLite is always a local file or memory database. PostgreSQL qualifies
    only on a loopback (or the test-compose ``postgres``) host and only when
    both the configured name and the name the server reports contain
    ``test`` (the rule ``tests/conftest.py`` enforces). A Unix socket, any
    other host, or a production-named database never qualifies.
    """
    if dialect == "sqlite":
        return True
    if dialect != "postgresql":
        return False
    names = [str(url_database or "").lower(), str(server_database or "").lower()]
    return (str(host or "").lower() in LOCAL_TEST_DATABASE_HOSTS
            and all(name and "test" in name for name in names))


def database_environment(session):
    """The authoritative facts about the connected database and runtime (pure)."""
    bind = session.get_bind()
    dialect, url = bind.dialect.name, bind.url
    server_database = session.execute(text("SELECT current_database()")).scalar_one() \
        if dialect == "postgresql" else None
    facts = {"dialect": dialect, "host": url.host, "database": url.database, "server_database": server_database,
             "production_runtime": is_production_runtime()}
    facts["local_test_database"] = is_local_test_database(
        dialect=dialect, host=url.host, url_database=url.database, server_database=server_database)
    return facts


def _guard_environment(session, environment):
    """Refuse before anything is read or written unless the runtime and database allow ``environment``."""
    if environment not in ENVIRONMENTS:
        raise RehearsalError("a rehearsal runs only on local fixtures or an approved restore copy, never production")
    facts = database_environment(session)
    if facts["production_runtime"]:
        raise RehearsalError("a rehearsal never runs in a production runtime (is_production_runtime)")
    if environment == "fixtures" and not facts["local_test_database"]:
        # A 'fixtures' label never switches off the restore-copy controls on another database.
        raise RehearsalError("fixture rehearsals run only on a verified local test database; "
                             "any other database needs the restore_copy controls")
    return facts


# ---------------------------------------------------------------------------
# Preconditions (Phase 14 re-acceptance start checks)
# ---------------------------------------------------------------------------

def _finding(findings, check, status, scope, detail=None):
    findings.append({"check": check, "status": status, "scope": scope, "detail": detail})


def _privileges(session, role, table):
    row = session.execute(text(
        "SELECT has_table_privilege(:r, :t, 'INSERT'), has_table_privilege(:r, :t, 'UPDATE'), "
        "has_table_privilege(:r, :t, 'DELETE'), has_table_privilege(:r, :t, 'TRUNCATE')"),
        {"r": role, "t": table}).one()
    return dict(zip(("insert", "update", "delete", "truncate"), row))


def _role_findings(session, findings, runtime_role):
    if session.get_bind().dialect.name != "postgresql":
        _finding(findings, "restore_copy_database", "fail", "restore_copy",
                 "a restore-copy rehearsal runs on PostgreSQL, where the role separation is enforced")
        return
    current, superuser = session.execute(text(
        "SELECT current_user, rolsuper FROM pg_roles WHERE rolname = current_user")).one()
    broad = [t for t in PHASE14_TABLES
             if any(v for k, v in _privileges(session, current, t).items() if k != "insert")]
    missing = [t for t in PHASE14_TABLES if not _privileges(session, current, t)["insert"]]
    if superuser or broad or missing:
        _finding(findings, "migration_role_least_privilege", "fail", "restore_copy",
                 {"role": current, "superuser": bool(superuser), "update_delete_or_truncate": broad,
                  "insert_missing": missing})
    else:
        _finding(findings, "migration_role_least_privilege", "pass", "restore_copy", {"role": current})
    if not isinstance(runtime_role, str) or not runtime_role.strip():
        _finding(findings, "runtime_role_cannot_write_phase14", "fail", "restore_copy",
                 "name the application runtime role to prove it holds no INSERT on the Phase 14 tables")
        return
    exists = session.execute(text("SELECT count(*) FROM pg_roles WHERE rolname = :r"),
                             {"r": runtime_role}).scalar_one()
    if not exists or runtime_role == current:
        _finding(findings, "runtime_role_cannot_write_phase14", "fail", "restore_copy",
                 {"runtime_role": runtime_role, "exists": bool(exists), "is_the_migration_role": runtime_role == current})
        return
    writable = [t for t in PHASE14_TABLES if _privileges(session, runtime_role, t)["insert"]]
    _finding(findings, "runtime_role_cannot_write_phase14", "fail" if writable else "pass", "restore_copy",
             {"runtime_role": runtime_role, "insert_on": writable})


def rehearsal_preconditions(session, *, environment, runtime_role=None, writer_freeze_reference=None):
    """Every Phase 15 start check for ``environment`` (pure). Returns ``{"ready", "findings", ...}``.

    ``scope`` on each finding says whether a check gates local fixture runs
    (``local``), only restore-copy rehearsals (``restore_copy``), or is
    reported for the later cutover (``cutover``). Unknown environments are
    refused, any environment is refused in a production runtime
    (``is_production_runtime``), and ``fixtures`` is refused unless the
    connected database is a verified local test database (audit C1).
    """
    facts = _guard_environment(session, environment)
    restore = environment == "restore_copy"
    findings = []
    with session.no_autoflush:
        _finding(findings, "runtime_and_database_environment", "pass", "local", facts)
        try:
            _finding(findings, "credit_unit_equivalence", "pass", "local", verify_credit_unit_equivalence())
        except MigrationUnitError as exc:
            _finding(findings, "credit_unit_equivalence", "fail", "local", str(exc))
        pricing = pricing_unit_findings(session)
        _finding(findings, "pricing_in_internal_units", "fail" if pricing else "pass", "local", pricing or None)
        _finding(findings, "founder_test_credit_policy", "pass", "local", FOUNDER_TEST_POLICY)
        in_flight = session.execute(select(AIOperation.id).where(AIOperation.status == "started")
                                    .order_by(AIOperation.id)).scalars().all()
        if restore:
            _finding(findings, "no_in_flight_ai_operations", "fail" if in_flight else "pass", "restore_copy",
                     {"started_operations": in_flight})
        else:
            # Fixture runs: affected accounts quarantine (legacy_operation_in_flight); nothing is inferred.
            _finding(findings, "no_in_flight_ai_operations", "reported", "local", {"started_operations": in_flight})
        if restore:
            frozen = isinstance(writer_freeze_reference, str) and bool(writer_freeze_reference.strip())
            _finding(findings, "legacy_writers_frozen_before_snapshot", "pass" if frozen else "fail", "restore_copy",
                     writer_freeze_reference if frozen else
                     "attest that every D04 writer, including TurnBilling, was frozen before the snapshot")
            _role_findings(session, findings, runtime_role)
        else:
            for check in ("legacy_writers_frozen_before_snapshot", "migration_role_least_privilege",
                          "runtime_role_cannot_write_phase14"):
                _finding(findings, check, "not_applicable", "restore_copy", "fixture data has no live writer")
        reviewers = session.execute(text(
            "SELECT count(*) FROM billing_staff_permission_grants g WHERE g.permission = :p AND NOT EXISTS "
            "(SELECT 1 FROM billing_staff_permission_revocations r WHERE r.grant_id = g.id)"),
            {"p": REVIEW_PERMISSION}).scalar_one()
        _finding(findings, "migration_review_holder", "reported", "cutover",
                 {"unrevoked_review_grants": int(reviewers),
                  "needed_only_if": "an account needs a legacy_unattributed review"})
        for check, detail in (
                ("approved_entitlement_definitions", "Free and the 300K offer, before any account is cutover_eligible"),
                ("pre_unit_boundary_rule", "a founder rule for live pre-2026-05-08 value, sized by the F4 report"),
                ("processor_verification", "only for mapped_pending_processor accounts (separately authorized)")):
            _finding(findings, check, "deferred", "cutover", detail)
    return {"environment": environment, "rehearsal_version": REHEARSAL_VERSION,
            "ready": not any(f["status"] == "fail" for f in findings), "findings": findings}


# ---------------------------------------------------------------------------
# Orchestration (run order: archive, establish, backfill, map)
# ---------------------------------------------------------------------------

def _step(session, steps, step, subject, command):
    for attempt in range(1, RETRY_ATTEMPTS + 1):
        try:
            outcome = command()
            session.commit()
        except MigrationRetryError:
            session.rollback()
            if attempt == RETRY_ATTEMPTS:
                raise RehearsalStepError(step, subject, list(steps)) from None
            continue
        except Exception as exc:
            session.rollback()
            raise RehearsalStepError(step, subject, list(steps)) from exc
        steps.append({"step": step, "subject": subject, **outcome, "attempts": attempt})
        return outcome


def _newer_runs_holding_targets(session, run, targets):
    """Establishments of the targets recorded by any run started after ``run`` (audit C3)."""
    started = _utc(run.started_at)
    rows = session.execute(
        select(BillingMigrationEstablishment.organization_id, BillingMigrationRun.id, BillingMigrationRun.started_at)
        .join(BillingMigrationRun, BillingMigrationRun.id == BillingMigrationEstablishment.run_id)
        .where(BillingMigrationEstablishment.organization_id.in_(targets), BillingMigrationRun.id != run.id)
    ).all()
    return sorted({(org, other) for org, other, other_started in rows if _utc(other_started) >= started})


def _owned_establishment(session, run_id, organization_id):
    """The organization's latest establishment, which must belong to this run before it is used (audit C3)."""
    latest = session.execute(
        select(BillingMigrationEstablishment).where(BillingMigrationEstablishment.organization_id == organization_id)
        .order_by(BillingMigrationEstablishment.created_at.desc(), BillingMigrationEstablishment.id.desc()).limit(1)
    ).scalar_one_or_none()
    if latest is None or latest.run_id != run_id:
        raise RehearsalSupersededError(
            f"organization {organization_id} was established by another run; this run cannot use that evidence")
    return latest


def _require_own_mapping(session, run_id, row):
    """The mapping just returned must name this run's establishment (re-acceptance R1).

    Phase 14's ``map_legacy_plan`` reads the latest establishment in its own
    statement and only flushes; ``_step`` commits after the command returns.
    Under READ COMMITTED another run can commit a newer establishment between
    ``_owned_establishment`` and that read, so the row it wrote is checked here,
    inside the same transaction: raising makes ``_step`` roll back the mapping
    and its idempotency claim together. The establishment's ``run_id`` is
    immutable evidence, so this check cannot itself race.
    """
    establishment = session.get(BillingMigrationEstablishment, row.establishment_id)
    if establishment is None or establishment.run_id != run_id or row.run_id != run_id:
        raise RehearsalSupersededError(
            f"the plan mapping for organization {row.organization_id} would reference another run's "
            "establishment; this run cannot use that evidence")
    return row


def run_rehearsal(session, *, run_key, authorization_reference, operator_user_id, organization_ids, environment,
                  test_activity_attestation=None, runtime_role=None, writer_freeze_reference=None,
                  actor_id="phase15-rehearsal", sample_size=3):
    """Run one rehearsal end to end; each step commits on its own. Returns the census, steps, and report.

    ``organization_ids`` is the explicit target list (D16 "for each explicit
    target organization"). Repeating the call with the same arguments
    resumes the same run after a failure. A new ``run_key`` over the same
    evidence is the rerun whose ``rerun_proof`` must show zero new entries.
    """
    if isinstance(organization_ids, str) or not organization_ids:
        raise RehearsalError("name the explicit target organizations")
    targets = sorted(set(organization_ids))
    preconditions = rehearsal_preconditions(session, environment=environment, runtime_role=runtime_role,
                                            writer_freeze_reference=writer_freeze_reference)
    if not preconditions["ready"]:
        session.rollback()
        raise RehearsalPreconditionError("a rehearsal precondition failed", preconditions["findings"])
    before = rehearsal_census(session)
    session.rollback()  # end the read transaction; every step below runs in its own
    steps = []
    reference = authorization_reference if environment == "fixtures" else \
        f"{authorization_reference} (restore copy; writer freeze: {writer_freeze_reference.strip()})"
    holder = {}

    def start():
        run, state = start_migration_run(session, run_key=run_key, authorization_reference=reference,
                                         actor_type="system", actor_id=actor_id, operator_user_id=operator_user_id)
        holder["run_id"] = run.id
        return {"state": state, "run_id": run.id}

    _step(session, steps, "start_run", run_key, start)
    run_id = holder["run_id"]
    # A resumed run never builds on records of a run that started after it (audit C3): fail closed, write nothing.
    superseded = _newer_runs_holding_targets(session, session.get(BillingMigrationRun, run_id), targets)
    session.rollback()
    if superseded:
        raise RehearsalSupersededError(
            f"a newer run already holds establishments of these targets: {superseded}; start a new run instead")

    def archive():
        result = archive_legacy_payments(session, run_id=run_id, test_activity_attestation=test_activity_attestation)
        return {"state": "inserted" if result["archived"] else "unchanged", "archived": result["archived"],
                "unchanged": result["unchanged"], "findings": result["findings"]}

    _step(session, steps, "archive_payments", "all", archive)

    accounts = {}
    for organization_id in targets:
        def establish(organization_id=organization_id):
            row, state = establish_billing_account(session, run_id=run_id, organization_id=organization_id)
            accounts[organization_id] = (row.billing_account_id, row.outcome)
            return {"state": state, "outcome": row.outcome, "billing_account_id": row.billing_account_id}
        _step(session, steps, "establish", organization_id, establish)

    for organization_id in targets:
        account_id, _outcome = accounts[organization_id]
        if account_id is None:
            continue  # quarantined before any account exists: reported as not established

        def backfill(account_id=account_id, organization_id=organization_id):
            _owned_establishment(session, run_id, organization_id)
            row, state = backfill_billing_account(session, run_id=run_id, billing_account_id=account_id)
            return {"state": state, "outcome": row.outcome, "opened_total": int(row.opened_total)}
        _step(session, steps, "backfill", account_id, backfill)

    for organization_id in targets:
        account_id, outcome = accounts[organization_id]
        if account_id is None or outcome not in ("established", "unchanged"):
            continue

        def mapping(account_id=account_id, organization_id=organization_id):
            _owned_establishment(session, run_id, organization_id)
            row, state = map_legacy_plan(session, run_id=run_id, billing_account_id=account_id)
            _require_own_mapping(session, run_id, row)  # before _step commits (R1)
            return {"state": state, "outcome": row.outcome}
        _step(session, steps, "map_plan", account_id, mapping)

    after = rehearsal_census(session)
    archive_findings = next(s["findings"] for s in steps if s["step"] == "archive_payments")
    report = rehearsal_report(session, run_id=run_id, sample_size=sample_size, target_organization_ids=targets,
                              test_activity_attestation=test_activity_attestation,
                              archive_step_findings=archive_findings)
    session.rollback()
    return {"run_id": run_id, "environment": environment, "preconditions": preconditions, "steps": steps,
            "census_before": before, "census_after": after, "census_delta": _delta(before, after),
            "legacy_unchanged": before["legacy"]["fingerprint"] == after["legacy"]["fingerprint"],
            "report": report}


# ---------------------------------------------------------------------------
# Reports (pure)
# ---------------------------------------------------------------------------

def historical_value_by_state(session, *, at=None):
    """Pre-2026-05-08 value split into expired, live, and undetermined (re-acceptance F4; pure).

    A meter's value lives until one calendar month after its cycle reset
    (original terms); a lapsed cycle already expired and is never purchasing
    power, but it is reported here, never discarded. Persistent grants were
    sold non-expiring, so their remainder is live. A counter without a meter
    and a grant without a date have no cycle evidence: undetermined. The
    user-meter, user-counter, and grant totals reconcile exactly to the
    Phase 14 ``historical_value_population``; organization pool meters are
    reported in addition (the Phase 14 population lists users only).
    """
    with session.no_autoflush:
        at = _utc(at) if at is not None else _database_clock(session)  # the backfill's clock
        empty = lambda: {state: {"holders": 0, "amount": 0} for state in ("expired", "live", "undetermined")}
        out = {key: empty() for key in ("legacy_meter_absent", "pre_unit_boundary_meter",
                                        "pre_unit_boundary_organization_meter", "pre_unit_boundary_grant",
                                        "grant_date_missing")}

        def add(key, state, amount):
            out[key][state]["holders"] += 1
            out[key][state]["amount"] += amount

        def meter_state(meter):
            reset = _parsed(meter.get("cycle_reset_at")) if meter else None
            remaining = _int_or_none(meter.get("remaining")) if meter else None
            if reset is None or reset >= UNIT_BOUNDARY_AT or not remaining:
                return None, 0
            return ("expired" if add_calendar_months(reset, 1) <= at else "live"), remaining

        for user in session.execute(select(User).order_by(User.id)).scalars():
            meter = _meter(user.ui_preferences)
            persistent = session.execute(
                select(func.coalesce(func.sum(PersistentCreditGrant.remaining_amount), 0)).where(
                    PersistentCreditGrant.user_id == user.id, PersistentCreditGrant.status == "active")
            ).scalar_one()
            unexplained = int(user.credits_remaining or 0) - int(persistent)
            if meter is None and unexplained != 0:
                add("legacy_meter_absent", "undetermined", unexplained)
            state, amount = meter_state(meter)
            if state:
                add("pre_unit_boundary_meter", state, amount)
        for organization in session.execute(select(Organization).order_by(Organization.id)).scalars():
            state, amount = meter_state(_meter(organization.settings))
            if state:
                add("pre_unit_boundary_organization_meter", state, amount)
        for grant in session.execute(select(PersistentCreditGrant).where(
                PersistentCreditGrant.status == "active", PersistentCreditGrant.remaining_amount > 0)
                .order_by(PersistentCreditGrant.id)).scalars():
            granted_at = _utc(grant.granted_at)
            if granted_at is None:
                add("grant_date_missing", "undetermined", int(grant.remaining_amount))
            elif granted_at < UNIT_BOUNDARY_AT:
                add("pre_unit_boundary_grant", "live", int(grant.remaining_amount))
        phase14 = historical_value_population(session)
        reconciles = all(
            sum(out[key][state]["holders"] for state in out[key]) == phase14[key]["holders"]
            and sum(out[key][state]["amount"] for state in out[key]) == phase14[key]["amount"]
            for key in phase14)
        return {"as_of": at.isoformat(), "unit_boundary_at": UNIT_BOUNDARY_AT.isoformat(), "by_state": out,
                "phase14_population": phase14, "reconciles_to_phase14_population": reconciles,
                "rule": "nothing here is opened, converted, or discarded; live value waits for a founder rule"}


def _grant_payment_ids(result):
    """grant id -> legacy payment id, from the immutable evidence a result was decided on."""
    ids = {}
    for holder in (result.evidence_json or {}).get("holders") or []:
        for grant in holder.get("grants") or []:
            payment = grant.get("payment") or {}
            ids[grant.get("grant_id")] = payment.get("payment_id")
    return ids


def _latest_mapping(session, account_id):
    return session.execute(
        select(BillingMigrationPlanMapping).where(BillingMigrationPlanMapping.billing_account_id == account_id)
        .order_by(BillingMigrationPlanMapping.created_at.desc(), BillingMigrationPlanMapping.id.desc()).limit(1)
    ).scalar_one_or_none()


def _subscription_funding(mapping, member_id):
    if mapping is None:
        return "unmapped", []
    subject = next((s for s in mapping.mapping_json.get("subjects") or [] if s.get("user_id") == member_id), None)
    invoices = [p for p in (subject or {}).get("payments") or [] if p.get("source") == "subscription_invoice"]
    if not invoices:
        return "no_payment_evidence", []
    classes = {p.get("classification") for p in invoices}
    funding = "founder_test" if classes == {"test_activity"} else ("unarchived" if None in classes else "unverified")
    return funding, [p.get("payment_id") for p in invoices]


def _pool_funding(session, account_id, mapping):
    """Funding of an organization pool lot from its bound payer's attributed, archived invoices (audit C2).

    ``founder_test`` only when the account's one bound payer has at least one
    subscription invoice, every one of them attributed to this account by
    establishment and archived ``test_activity``, and no other subject of the
    account's plan mapping holds a paid subscription of its own. Anything
    mixed, missing, or ambiguous stays ``unverified`` (never guessed, never
    genuine). The lot itself (balance, terms, attribution) is only read.
    """
    binding = session.execute(select(BillingMigrationPayerBinding).where(
        BillingMigrationPayerBinding.billing_account_id == account_id)).scalar_one_or_none()
    if binding is None:
        return "no_payment_evidence", [], "no_bound_payer"
    invoices = session.execute(select(BillingMigrationPaymentArchive).where(
        BillingMigrationPaymentArchive.legacy_user_id == binding.payer_user_id,
        BillingMigrationPaymentArchive.source == "subscription_invoice")
        .order_by(BillingMigrationPaymentArchive.payment_id)).scalars().all()
    ids = [row.payment_id for row in invoices]
    if not invoices:
        return "no_payment_evidence", [], "payer_has_no_archived_subscription_invoice"
    attributed = set(session.execute(select(BillingMigrationPaymentAttribution.payment_id).where(
        BillingMigrationPaymentAttribution.billing_account_id == account_id,
        BillingMigrationPaymentAttribution.payment_id.in_(ids))).scalars())
    if attributed != set(ids):
        return "unverified", ids, "invoice_not_attributed_to_this_account"
    if {row.classification for row in invoices} != {"test_activity"}:
        return "unverified", ids, "invoices_not_all_attested_test_activity"
    others = [subject.get("user_id") for subject in ((mapping.mapping_json.get("subjects") or []) if mapping else [])
              if subject.get("subscription") and subject.get("user_id") != binding.payer_user_id
              and subject.get("plan_key") in SHARED_POOL_PLANS]
    if mapping is None:
        return "unverified", ids, "account_not_mapped"
    if others:
        return "unverified", ids, "another_member_holds_a_paid_subscription"
    return "founder_test", ids, "every_payer_invoice_attested_test_activity"


def founder_test_credit_separation(session):
    """Every migrated lot by funding evidence, and purchased credit and revenue with founder tests excluded (pure).

    Founder decision (2026-11-19). A lot funded only by payments archived
    ``test_activity`` is ``founder_test``: kept exactly as opened, identified,
    and excluded from customer revenue and genuine purchased credit.
    ``unverified`` payments stay unverified (neither test nor genuine).
    Genuine customer purchases need a verified customer payment, which no
    archive is (``verified_customer_payments`` is always 0), so genuine
    purchased credit and customer revenue are 0 until a separately authorized
    processor verification exists.
    """
    with session.no_autoflush:
        archives = {row.payment_id: row for row in session.execute(select(BillingMigrationPaymentArchive)).scalars()}
        lots, results, mappings, balances = [], {}, {}, {}
        for opening in session.execute(select(BillingMigrationOpening).order_by(
                BillingMigrationOpening.billing_account_id, BillingMigrationOpening.opening_key)).scalars():
            account_id = opening.billing_account_id
            if account_id not in balances:
                balances[account_id] = {lot.id: available + held for lot, available, held
                                        in _lot_balances(session, account_id)}
            payments, basis = [], None
            if opening.legacy_source_kind == "organization_recurring_meter":
                if account_id not in mappings:
                    mappings[account_id] = _latest_mapping(session, account_id)
                funding, payments, basis = _pool_funding(session, account_id, mappings[account_id])
            elif opening.legacy_source_kind == "persistent_credit_grant":
                if opening.account_result_id not in results:
                    results[opening.account_result_id] = _grant_payment_ids(
                        session.get(BillingMigrationAccountResult, opening.account_result_id))
                payment_id = results[opening.account_result_id].get(opening.legacy_source_id)
                payments = [payment_id] if payment_id else []
                archive = archives.get(payment_id)
                funding = "unarchived" if archive is None else (
                    "founder_test" if archive.classification == "test_activity" else "unverified")
            elif opening.lot_source_type == "subscription_recurring":
                if account_id not in mappings:
                    mappings[account_id] = _latest_mapping(session, account_id)
                funding, payments = _subscription_funding(mappings[account_id], opening.member_attribution_id)
            elif opening.lot_source_type == "free_recurring":
                funding = "not_purchased"
            else:
                funding = "reviewed_unattributed" if opening.lot_source_type == "legacy_unattributed" else "other"
            references = sorted({archives[p].classification_reference for p in payments
                                 if p in archives and archives[p].classification_reference})
            lots.append({
                "opening_id": opening.id, "lot_id": opening.lot_id, "billing_account_id": account_id,
                "lot_source_type": opening.lot_source_type, "legacy_source_kind": opening.legacy_source_kind,
                "legacy_source_id": opening.legacy_source_id, "original_amount": int(opening.original_amount),
                "opening_amount": int(opening.opening_amount),
                "current_balance": balances[account_id].get(opening.lot_id),
                "funding": funding, "funding_basis": basis, "payment_ids": payments,
                "attestation_references": references,
            })

        def bucket(predicate):
            chosen = [lot for lot in lots if predicate(lot)]
            return {"lots": len(chosen), "opening_units": sum(lot["opening_amount"] for lot in chosen),
                    "current_units": sum(lot["current_balance"] or 0 for lot in chosen)}

        purchased = lambda lot: lot["lot_source_type"] in PURCHASED_LOT_SOURCES
        revenue = defaultdict(lambda: defaultdict(int))
        for row in archives.values():
            key = "excluded_founder_test" if row.classification == "test_activity" else "unverified_not_revenue"
            revenue[key][(row.currency or "").lower()] += int(row.amount_paid_cents)
        return {
            "policy": FOUNDER_TEST_POLICY,
            "lots": lots,
            "purchased_credit": {
                # A genuine customer purchase needs a verified customer payment; no archive is one.
                "genuine_customer": {"lots": 0, "opening_units": 0, "current_units": 0},
                "excluded_founder_test": bucket(lambda lot: purchased(lot) and lot["funding"] == "founder_test"),
                "unverified": bucket(lambda lot: purchased(lot) and lot["funding"] in
                                     ("unverified", "unarchived", "unmapped", "no_payment_evidence")),
            },
            "promotional": bucket(lambda lot: lot["lot_source_type"] == "promotional"),
            "promotional_funded_by_founder_test": bucket(
                lambda lot: lot["lot_source_type"] == "promotional" and lot["funding"] == "founder_test"),
            "customer_revenue": {
                "verified_customer_cents_by_currency": {},
                "excluded_founder_test_cents_by_currency": dict(sorted(revenue["excluded_founder_test"].items())),
                "unverified_not_revenue_cents_by_currency": dict(sorted(revenue["unverified_not_revenue"].items())),
            },
            "balances_and_classifications_changed": False,
        }


def _archive_conflict(code, subject, detail, stage="payment_archive"):
    return {"stage": stage, "category": _category(code), "code": code, "organization_id": None,
            "billing_account_id": None, "subject": subject, "detail": detail}


def _conflicts(establishments, results, mappings, archive_plan, archive_step_findings=()):
    conflicts = []
    for stage, rows in (("establishment", establishments), ("backfill", results), ("plan_mapping", mappings)):
        for row in rows:
            for code in row.quarantine_codes_json:
                conflicts.append({"stage": stage, "category": _category(code["code"]), "code": code["code"],
                                  "organization_id": row.organization_id,
                                  "billing_account_id": row.billing_account_id,
                                  "subject": code.get("subject"), "detail": code.get("detail")})
    for item in archive_plan["payments"]:
        if item["state"] == "changed":
            conflicts.append({"stage": "payment_archive", "category": "payment", "code": "archived_payment_changed",
                              "organization_id": None, "billing_account_id": None, "subject": item["payment_id"],
                              "detail": None})
    for payment_id in archive_plan["archived_payment_missing"]:
        conflicts.append({"stage": "payment_archive", "category": "payment", "code": "archived_payment_missing",
                          "organization_id": None, "billing_account_id": None, "subject": payment_id,
                          "detail": None})
    # Audit C4: the same attestation conflicts the Phase 14 archive command reports, recomputed from the run's
    # attestation, then every step-level finding verbatim so nothing the command reported is omitted.
    if archive_plan["attestation"] is not None:
        for item in archive_plan["payments"]:
            if item["state"] == "unchanged" and item["archived_classification"] != item["classification"]:
                conflicts.append(_archive_conflict(
                    "classification_differs_from_archive", item["payment_id"],
                    {"archived": item["archived_classification"], "attested": item["classification"]}))
        for payer in archive_plan["attested_payers_without_payments"]:
            conflicts.append(_archive_conflict("attested_payer_without_payments", payer, None))
    seen = {(c["code"], c["subject"]) for c in conflicts if c["stage"] == "payment_archive"}
    for finding in archive_step_findings or ():
        if (finding["code"], finding.get("subject")) not in seen:
            conflicts.append(_archive_conflict(finding["code"], finding.get("subject"), finding.get("detail"),
                                               stage="payment_archive_step"))
    return conflicts


def _cycle(opening):
    return f"{_utc(opening.available_at).isoformat()}/{_utc(opening.expires_at).isoformat()}" \
        if opening.expires_at is not None else "non_expiring"


def _account_balances(session, result, openings):
    sources = (result.evidence_json or {}).get("sources") or []
    conservation = result.conservation_json or {}
    view = _credit_view(_lot_balances(session, result.billing_account_id), _utc(result.snapshot_at), None)
    reversed_total = sum(int((s.get("grant") or {}).get("original_amount") or 0)
                         for s in sources if s.get("classification") == "reversed")
    return {
        "billing_account_id": result.billing_account_id, "outcome": result.outcome,
        "pre": {"accepted_recurring": int(conservation.get("accepted_legacy_recurring_remaining") or 0),
                "accepted_persistent": int(conservation.get("accepted_legacy_persistent_remaining") or 0),
                "approved_adjustments": int(conservation.get("approved_migration_adjustments") or 0),
                "expired_recurring": sum(int(s.get("expired_amount") or 0) for s in sources
                                         if s.get("classification") == "expired_recurring_value"),
                "reversed_grants": reversed_total},
        "post": {"available": view["available"], "held": view["held"],
                 "settled": sum(int(v) for v in (conservation.get("settled_usage_by_operation") or {}).values()),
                 "expired": 0, "reversed": 0,
                 "opened_by_this_run": sum(int(o.opening_amount) for o in openings)},
        "balance_exact": conservation.get("balance_exact"),
    }


def _proof(session, result, openings):
    entries = {row.id: row for row in session.execute(select(CreditLedgerEntry).where(
        CreditLedgerEntry.id.in_([o.ledger_entry_id for o in openings]))).scalars()} if openings else {}
    return {
        "billing_account_id": result.billing_account_id, "outcome": result.outcome,
        "evidence_fingerprint": result.evidence_fingerprint,
        "input_evidence": {"sources": [{k: s.get(k) for k in ("kind", "legacy_source_id", "classification",
                                                              "member_attribution_id")}
                                       for s in (result.evidence_json or {}).get("sources") or []],
                           "holders": [h.get("user_id") for h in (result.evidence_json or {}).get("holders") or []]},
        "target_entries": [{
            "opening_key": o.opening_key, "legacy_source_kind": o.legacy_source_kind,
            "legacy_source_id": o.legacy_source_id, "lot_id": o.lot_id, "lot_source_type": o.lot_source_type,
            "opening_amount": int(o.opening_amount), "ledger_entry_id": o.ledger_entry_id,
            "entry_type": entries[o.ledger_entry_id].entry_type if o.ledger_entry_id in entries else None,
            "available_delta": int(entries[o.ledger_entry_id].available_delta) if o.ledger_entry_id in entries
            else None,
        } for o in sorted(openings, key=lambda o: o.opening_key)],
        "conservation": result.conservation_json,
        "quarantine_codes": [c["code"] for c in result.quarantine_codes_json],
    }


def _compatibility(session, results):
    by_field = defaultdict(Counter)
    drift = []
    for result in results:
        owners = (result.evidence_json or {}).get("owners") or {}
        zero = {tuple(item) for item in (result.evidence_json or {}).get("zero_cycles") or []}
        report = compare_legacy_compatibility(session, billing_account_id=result.billing_account_id,
                                              at=_utc(result.snapshot_at), value_owners=owners, zero_cycles=zero)
        for item in report["comparisons"]:
            by_field[item["field"]][item["classification"]] += 1
        stored = (result.comparison_json or {}).get("summary")
        if stored is not None and stored != report["summary"]:
            drift.append({"billing_account_id": result.billing_account_id, "stored": stored,
                          "recomputed": report["summary"]})
    return {"by_field": {field: dict(sorted(counts.items())) for field, counts in sorted(by_field.items())},
            "drift_from_stored_results": drift}


def _stale_claims(session):
    registry = db.metadata.tables["idempotency_registry"]
    return [{"namespace": ns, "key": key, "state": state} for ns, key, state in session.execute(
        select(registry.c.namespace, registry.c.key, registry.c.state)
        .where(registry.c.namespace.in_(MIGRATION_NAMESPACES), registry.c.state != "completed")
        .order_by(registry.c.namespace, registry.c.key))]


def rehearsal_report(session, *, run_id, sample_size=3, target_organization_ids=None, test_activity_attestation=None,
                     archive_step_findings=None):
    """Pure D16 reconciliation report of one rehearsal run (see the module docstring for every item).

    ``test_activity_attestation`` is the attestation the run archived with; its
    conflicts with earlier archives are recomputed here, and
    ``archive_step_findings`` (the archive step's own findings) are carried in
    verbatim, so the report lists every conflict the commands reported (C4).
    """
    with session.no_autoflush:
        base = migration_run_report(session, run_id=run_id)
        run = session.get(BillingMigrationRun, run_id)
        establishments = session.execute(select(BillingMigrationEstablishment).where(
            BillingMigrationEstablishment.run_id == run.id).order_by(
            BillingMigrationEstablishment.organization_id)).scalars().all()
        results = session.execute(select(BillingMigrationAccountResult).where(
            BillingMigrationAccountResult.run_id == run.id).order_by(
            BillingMigrationAccountResult.billing_account_id)).scalars().all()
        mappings = session.execute(select(BillingMigrationPlanMapping).where(
            BillingMigrationPlanMapping.run_id == run.id).order_by(
            BillingMigrationPlanMapping.billing_account_id)).scalars().all()
        openings = defaultdict(list)
        for opening in session.execute(select(BillingMigrationOpening).where(
                BillingMigrationOpening.run_id == run.id)).scalars():
            openings[opening.billing_account_id].append(opening)
        archive_plan = plan_payment_archive(session, test_activity_attestation=test_activity_attestation)

        by_account = {}
        for r in results:
            sums = Counter()
            for o in openings[r.billing_account_id]:
                sums[o.lot_source_type] += int(o.opening_amount)
            by_account[r.billing_account_id] = {"outcome": r.outcome, "opened_total": int(r.opened_total),
                                                "opened_by_source": dict(sorted(sums.items()))}
        by_currency = defaultdict(lambda: {"payments": 0, "amount_paid_cents": 0, "amount_due_cents": 0,
                                           "discount_cents": 0})
        for result in results:
            for currency, money in ((result.conservation_json or {}).get("money_by_currency") or {}).items():
                for key in by_currency[currency]:
                    by_currency[currency][key] += int(money.get(key) or 0)
        by_plan = defaultdict(lambda: {"accounts": 0, "opened_total": 0})
        opened = {r.billing_account_id: int(r.opened_total) for r in results}
        for mapping in mappings:
            key = mapping.legacy_plan_key or f"({mapping.outcome})"
            by_plan[key]["accounts"] += 1
            by_plan[key]["opened_total"] += opened.get(mapping.billing_account_id, 0)
        by_period = defaultdict(lambda: {"lots": 0, "amount": 0})
        for rows in openings.values():
            for o in rows:
                by_period[_cycle(o)]["lots"] += 1
                by_period[_cycle(o)]["amount"] += int(o.opening_amount)

        balances = [_account_balances(session, r, openings[r.billing_account_id]) for r in results]
        totals = {side: {key: sum(b[side][key] for b in balances) for key in balances[0][side]} if balances else {}
                  for side in ("pre", "post")}

        conflicts = _conflicts(establishments, results, mappings, archive_plan, archive_step_findings)
        duplicates = {
            "duplicate_external_references": sorted({c["subject"] for c in conflicts
                                                     if c["code"] == "duplicate_external_reference"}),
            "sources_opened_elsewhere": sorted({c["subject"] for c in conflicts
                                                if c["code"] == "legacy_source_opened_elsewhere"}),
            "sources_opened_more_than_once": base["sources_opened_more_than_once"],
            "idempotency_claims_not_completed": _stale_claims(session),
            # Audit C3: a mapping of this run must name this run's own establishment.
            "cross_run_plan_mappings": sorted(
                m.billing_account_id for m in mappings
                if (session.get(BillingMigrationEstablishment, m.establishment_id) is None
                    or session.get(BillingMigrationEstablishment, m.establishment_id).run_id != run.id)),
        }
        proofs = []
        for outcome in ("opened", "unchanged", "quarantined"):
            chosen = [r for r in results if r.outcome == outcome][:max(0, int(sample_size))]
            proofs.extend(_proof(session, r, openings[r.billing_account_id]) for r in chosen)
        targets = sorted(target_organization_ids or [])
        established_orgs = {e.organization_id for e in establishments}
        return {
            **base,
            "rehearsal_version": REHEARSAL_VERSION,
            "target_organizations": targets,
            "targets_without_establishment": [o for o in targets if o not in established_orgs],
            "organizations_not_established": sorted({e.organization_id for e in establishments
                                                     if e.billing_account_id is None}),
            "sums": {"by_account": by_account, "by_source": base["opened_by_source"],
                     "by_currency": dict(sorted(by_currency.items())), "by_plan": dict(sorted(by_plan.items())),
                     "by_period": dict(sorted(by_period.items()))},
            "balances": {"accounts": balances, "totals": totals},
            "duplicates_and_idempotency": duplicates,
            "unresolved_conflicts": conflicts,
            "unresolved_by_category": dict(sorted(Counter(c["category"] for c in conflicts).items())),
            "account_proofs": proofs,
            "compatibility": _compatibility(session, results),
            "historical_value_by_state": historical_value_by_state(session),
            "founder_test_separation": founder_test_credit_separation(session),
        }


def rerun_proof(session, *, first_run_id, second_run_id):
    """Pure proof that a second run over the same evidence wrote nothing new and reproduced every decision."""
    with session.no_autoflush:
        def rows(model, run_id):
            return session.execute(select(model).where(model.run_id == run_id)).scalars().all()

        new_openings = rows(BillingMigrationOpening, second_run_id)
        new_archives = rows(BillingMigrationPaymentArchive, second_run_id)
        first = {r.billing_account_id: r for r in rows(BillingMigrationAccountResult, first_run_id)}
        second = {r.billing_account_id: r for r in rows(BillingMigrationAccountResult, second_run_id)}
        first_maps = {m.billing_account_id: m for m in rows(BillingMigrationPlanMapping, first_run_id)}
        second_maps = {m.billing_account_id: m for m in rows(BillingMigrationPlanMapping, second_run_id)}
        first_est = {e.organization_id: e for e in rows(BillingMigrationEstablishment, first_run_id)}
        second_est = {e.organization_id: e for e in rows(BillingMigrationEstablishment, second_run_id)}
        differences = []
        for account_id in sorted(set(first) | set(second)):
            a, b = first.get(account_id), second.get(account_id)
            if a is None or b is None:
                differences.append({"billing_account_id": account_id, "reason": "account_not_in_both_runs"})
                continue
            if a.evidence_fingerprint != b.evidence_fingerprint:
                differences.append({"billing_account_id": account_id, "reason": "evidence_fingerprint_differs"})
            expected = "quarantined" if a.outcome == "quarantined" else "unchanged"
            if b.outcome != expected or b.opened_count != 0:
                differences.append({"billing_account_id": account_id, "reason": "rerun_outcome",
                                    "first": a.outcome, "second": b.outcome, "opened": b.opened_count})
        def decision(mapping):
            # A mapping names its run's establishment and credit result; the decision is everything else.
            evidence = {k: v for k, v in mapping.mapping_json.items() if k not in ("establishment_id",
                                                                                 "credit_balances")}
            return (mapping.outcome, mapping.legacy_plan_key, _fingerprint(evidence),
                    _fingerprint(mapping.unresolved_json), _fingerprint(mapping.quarantine_codes_json))

        for account_id in sorted(set(first_maps) | set(second_maps)):
            a, b = first_maps.get(account_id), second_maps.get(account_id)
            if a is None or b is None or decision(a) != decision(b):
                differences.append({"billing_account_id": account_id, "reason": "plan_mapping_differs"})
        for organization_id in sorted(set(first_est) | set(second_est)):
            a, b = first_est.get(organization_id), second_est.get(organization_id)
            if a is None or b is None or a.evidence_fingerprint != b.evidence_fingerprint \
                    or b.outcome not in ("unchanged", "quarantined") \
                    or (b.outcome == "quarantined") != (a.outcome == "quarantined"):
                differences.append({"organization_id": organization_id, "reason": "establishment_differs"})
        ledger_entries = session.execute(select(func.count()).select_from(CreditLedgerEntry).where(
            CreditLedgerEntry.id.in_([o.ledger_entry_id for o in new_openings]))).scalar_one() if new_openings else 0
        return {"first_run_id": first_run_id, "second_run_id": second_run_id,
                "new_openings": len(new_openings), "new_ledger_entries": int(ledger_entries),
                "new_payment_archives": len(new_archives), "differences": differences,
                "zero_new_entries": not new_openings and not new_archives,
                "deterministic": not differences}
