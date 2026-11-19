"""Inactive Phase 14 evidence for the legacy backfill (D16).

Nine immutable tables record how legacy billing ownership and preserved
legacy credit value entered the organization-owned Phase 3 authorities, and
how legacy payments and plans are preserved for the cutover:

* ``billing_migration_runs``: one controlled, explicitly authorized run, with
  the credit-unit basis established by Gate 1, the founder-approved expiry
  policy (purchased credit keeps its original terms), and its operator;
* ``billing_migration_establishments``: one decision per run and organization
  (D16 step 1): the organization's billing account, created when absent, and
  the evidence it was established from;
* ``billing_migration_payer_bindings``: a legacy payer's processor customer
  bound to exactly one billing account (globally unique);
* ``billing_migration_payment_attributions``: each legacy payment receipt
  attributed to exactly one billing account (globally unique), copying its
  identity and amounts as immutable evidence;
* ``billing_migration_account_results``: one decision per run and billing
  account (opened, unchanged, or quarantined), with the evidence fingerprint,
  the D16 conservation proof, and the Phase 13 comparison it was checked by;
* ``billing_migration_openings``: one row per ``migration_opening`` lot, with
  its legacy source identity (each legacy source opens at most once, across
  every billing account), evidence rank, expiry basis, source fingerprint,
  calculation, and the exact lot and ledger entry it authorizes;
* ``billing_migration_reviews``: the documented reconciliation review that is
  the only way a ``legacy_unattributed`` lot can be opened;
* ``billing_migration_payment_archives``: each legacy payment row preserved
  exactly as stored (founder decision 2026-11-18: a legacy archive, never a
  Phase 5.2 financial transaction), classified ``test_activity`` only on an
  explicit founder attestation naming its payer, else ``unverified``; no
  payment is a verified customer payment without a separately authorized
  processor verification, and nothing missing (event, tax, fees, lines) is
  filled in;
* ``billing_migration_plan_mappings``: one evidence-backed mapping per run and
  established billing account of the legacy plan, subscription, entitlements,
  and seats onto the organization, with every term the legacy records cannot
  prove (subscription dates, paid seats, payment details) left unresolved.

The Phase 3 ledger stays the only balance authority and the Phase 3 billing
account the only payer authority. Nothing in live routes, the AI runtime,
webhooks, jobs, or startup writes to or reads from these tables.
"""

import uuid
from datetime import datetime, timezone

from . import db


ALGORITHM_VERSION = "jaspen.billing.migration.v1"
# Gate 1 (2026-11-17): legacy stored integers and ledger integers are the same
# unit, the legacy internal unit, of which 1,000 make one displayed credit.
CREDIT_UNIT_BASIS = "jaspen.legacy_internal_unit.v1"
UNITS_PER_DISPLAYED_CREDIT = 1000

OUTCOMES = ("opened", "unchanged", "quarantined")
ESTABLISHMENT_OUTCOMES = ("established", "unchanged", "quarantined")
# Founder decision (2026-11-18): purchased credit keeps its original expiration
# terms; genuinely non-expiring packs, including the 300K offer, stay
# non-expiring. No other migration expiry policy exists.
EXPIRY_POLICY = "original_terms"
EXPIRY_BASES = ("legacy_cycle_end", "non_expiring_legacy_contract")
LEGACY_SOURCE_KINDS = (
    "user_recurring_meter", "organization_recurring_meter", "persistent_credit_grant", "reviewed_unattributed",
)
OPENING_LOT_SOURCES = (
    "free_recurring", "subscription_recurring", "credit_pack_purchase", "promotional", "legacy_unattributed",
)
REVIEW_PERMISSION = "billing.migration.review"
# Founder decision (2026-11-18): historical payments are archived, never turned into financial transactions.
# ``test_activity`` needs an explicit founder attestation naming the payer; everything else stays
# ``unverified``. A verified customer payment needs a separately authorized processor verification.
PAYMENT_CLASSIFICATIONS = ("test_activity", "unverified")
PLAN_MAPPING_OUTCOMES = ("mapped", "mapped_pending_processor", "quarantined")


def _quoted(values):
    return ", ".join(f"'{value}'" for value in values)


def _now():
    return datetime.now(timezone.utc)


def _id():
    return db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))


def _ref(name, table, *, nullable=False, deferred=False):
    options = {"deferrable": True, "initially": "DEFERRED"} if deferred else {}
    return db.Column(
        db.String(36),
        db.ForeignKey(f"{table}.id", name=name, ondelete="RESTRICT", **options),
        nullable=nullable,
    )


_FINGERPRINT = "length({0}) = 64 AND {0} = lower({0})"


class BillingMigrationRun(db.Model):
    """One explicit, operator-authorized backfill run; it opens nothing by itself."""

    __tablename__ = "billing_migration_runs"

    id = _id()
    run_key = db.Column(db.String(128), nullable=False)
    algorithm_version = db.Column(db.String(64), nullable=False)
    credit_unit_basis = db.Column(db.String(64), nullable=False)
    units_per_displayed_credit = db.Column(db.Integer, nullable=False)
    expiry_policy = db.Column(db.String(40), nullable=False)
    authorization_reference = db.Column(db.String(255), nullable=False)
    actor_type = db.Column(db.String(40), nullable=False)
    actor_id = db.Column(db.String(255), nullable=False)
    # The internal person who executes the run; never the reviewer of a review it consumes.
    operator_user_id = _ref("fk_billing_migration_runs_operator", "users")
    request_fingerprint = db.Column(db.String(64), nullable=False)
    idempotency_registry_id = _ref("fk_billing_migration_runs_registry", "idempotency_registry")
    started_at = db.Column(db.DateTime(timezone=True), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("run_key", name="uq_billing_migration_runs_key"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_billing_migration_runs_registry"),
        db.CheckConstraint(
            f"algorithm_version = '{ALGORITHM_VERSION}' AND credit_unit_basis = '{CREDIT_UNIT_BASIS}' "
            f"AND units_per_displayed_credit = {UNITS_PER_DISPLAYED_CREDIT}",
            name="ck_billing_migration_runs_basis",
        ),
        db.CheckConstraint(
            f"expiry_policy = '{EXPIRY_POLICY}'",
            name="ck_billing_migration_runs_policy",
        ),
        db.CheckConstraint(
            "actor_type = 'system' AND length(trim(actor_id)) > 0 AND length(trim(run_key)) > 0 "
            "AND length(trim(authorization_reference)) > 0 AND " + _FINGERPRINT.format("request_fingerprint"),
            name="ck_billing_migration_runs_provenance",
        ),
    )


class BillingMigrationEstablishment(db.Model):
    """D16 step 1 for one organization in one run: its billing account and payer evidence."""

    __tablename__ = "billing_migration_establishments"

    id = _id()
    run_id = _ref("fk_billing_migration_establishments_run", "billing_migration_runs")
    organization_id = _ref("fk_billing_migration_establishments_organization", "organizations")
    billing_account_id = _ref("fk_billing_migration_establishments_account", "billing_accounts", nullable=True)
    outcome = db.Column(db.String(24), nullable=False)
    account_created = db.Column(db.Boolean, nullable=False)
    evidence_fingerprint = db.Column(db.String(64), nullable=False)
    evidence_json = db.Column(db.JSON, nullable=False)
    quarantine_codes_json = db.Column(db.JSON, nullable=False)
    idempotency_registry_id = _ref("fk_billing_migration_establishments_registry", "idempotency_registry")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("run_id", "organization_id", name="uq_billing_migration_establishments_run_org"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_billing_migration_establishments_registry"),
        db.CheckConstraint(f"outcome IN ({_quoted(ESTABLISHMENT_OUTCOMES)})",
                           name="ck_billing_migration_establishments_outcome"),
        db.CheckConstraint(
            "(outcome IN ('established', 'unchanged') AND billing_account_id IS NOT NULL) OR "
            "(outcome = 'quarantined' AND NOT account_created)",
            name="ck_billing_migration_establishments_shape",
        ),
        db.CheckConstraint("outcome = 'established' OR NOT account_created",
                           name="ck_billing_migration_establishments_created"),
        db.CheckConstraint(_FINGERPRINT.format("evidence_fingerprint"),
                           name="ck_billing_migration_establishments_fingerprint"),
        db.Index("ix_billing_migration_establishments_org", "organization_id", "created_at"),
        db.Index("ix_billing_migration_establishments_account", "billing_account_id"),
    )


class BillingMigrationPayerBinding(db.Model):
    """A legacy payer's processor customer, bound to exactly one billing account (globally unique)."""

    __tablename__ = "billing_migration_payer_bindings"

    id = _id()
    establishment_id = _ref("fk_billing_migration_payer_bindings_establishment", "billing_migration_establishments")
    billing_account_id = _ref("fk_billing_migration_payer_bindings_account", "billing_accounts")
    payer_user_id = _ref("fk_billing_migration_payer_bindings_payer", "users")
    processor = db.Column(db.String(32), nullable=False)
    processor_customer_id = db.Column(db.String(255), nullable=False)
    # True when establishment wrote the customer onto the account; such a customer is Phase 14 output, never
    # legacy payer evidence. False when the account already carried it (external evidence, rank 1).
    customer_assigned_by_migration = db.Column(db.Boolean, nullable=False)
    evidence_json = db.Column(db.JSON, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("payer_user_id", name="uq_billing_migration_payer_bindings_payer"),
        db.UniqueConstraint("processor", "processor_customer_id", name="uq_billing_migration_payer_bindings_customer"),
        db.UniqueConstraint("billing_account_id", name="uq_billing_migration_payer_bindings_account"),
        db.CheckConstraint("processor = 'stripe' AND length(trim(processor_customer_id)) > 0",
                           name="ck_billing_migration_payer_bindings_identity"),
    )


class BillingMigrationPaymentAttribution(db.Model):
    """One legacy payment receipt attributed to exactly one billing account; its identity and amounts copied."""

    __tablename__ = "billing_migration_payment_attributions"

    id = _id()
    establishment_id = _ref("fk_billing_migration_payment_attributions_establishment",
                            "billing_migration_establishments")
    payer_binding_id = _ref("fk_billing_migration_payment_attributions_binding", "billing_migration_payer_bindings")
    billing_account_id = _ref("fk_billing_migration_payment_attributions_account", "billing_accounts")
    # The legacy ``payments`` row (archive, never written); no foreign key so the archive is never constrained.
    payment_id = db.Column(db.String(36), nullable=False)
    external_reference = db.Column(db.String(255), nullable=False)
    source = db.Column(db.String(40), nullable=False)
    currency = db.Column(db.String(8), nullable=False)
    amount_paid_cents = db.Column(db.BigInteger, nullable=False)
    amount_due_cents = db.Column(db.BigInteger, nullable=False)
    discount_cents = db.Column(db.BigInteger, nullable=False)
    is_comped = db.Column(db.Boolean, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("payment_id", name="uq_billing_migration_payment_attributions_payment"),
        db.UniqueConstraint("external_reference", name="uq_billing_migration_payment_attributions_reference"),
        db.CheckConstraint(
            "length(trim(payment_id)) > 0 AND length(trim(external_reference)) > 0 AND length(trim(source)) > 0 "
            "AND amount_paid_cents >= 0 AND amount_due_cents >= 0 AND discount_cents >= 0",
            name="ck_billing_migration_payment_attributions_shape",
        ),
        db.Index("ix_billing_migration_payment_attributions_account", "billing_account_id"),
    )


class BillingMigrationAccountResult(db.Model):
    """The run's decision for one organization billing account, with its evidence and proofs."""

    __tablename__ = "billing_migration_account_results"

    id = _id()
    run_id = _ref("fk_billing_migration_account_results_run", "billing_migration_runs")
    billing_account_id = _ref("fk_billing_migration_account_results_account", "billing_accounts")
    organization_id = _ref("fk_billing_migration_account_results_organization", "organizations")
    outcome = db.Column(db.String(24), nullable=False)
    snapshot_at = db.Column(db.DateTime(timezone=True), nullable=False)
    evidence_fingerprint = db.Column(db.String(64), nullable=False)
    evidence_json = db.Column(db.JSON, nullable=False)
    quarantine_codes_json = db.Column(db.JSON, nullable=False)
    conservation_json = db.Column(db.JSON, nullable=False)
    comparison_json = db.Column(db.JSON, nullable=False)
    opened_count = db.Column(db.Integer, nullable=False)
    opened_total = db.Column(db.BigInteger, nullable=False)
    credit_reconciled = db.Column(db.Boolean, nullable=False)
    cutover_eligible = db.Column(db.Boolean, nullable=False)
    idempotency_registry_id = _ref("fk_billing_migration_account_results_registry", "idempotency_registry")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("run_id", "billing_account_id", name="uq_billing_migration_account_results_run_account"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_billing_migration_account_results_registry"),
        db.CheckConstraint(f"outcome IN ({_quoted(OUTCOMES)})", name="ck_billing_migration_account_results_outcome"),
        db.CheckConstraint(
            "(outcome = 'opened' AND opened_count > 0 AND opened_total > 0) OR "
            "(outcome <> 'opened' AND opened_count = 0 AND opened_total = 0)",
            name="ck_billing_migration_account_results_opened",
        ),
        db.CheckConstraint(
            "(outcome <> 'quarantined' OR NOT credit_reconciled) AND (NOT cutover_eligible OR credit_reconciled)",
            name="ck_billing_migration_account_results_eligibility",
        ),
        db.CheckConstraint(_FINGERPRINT.format("evidence_fingerprint"),
                           name="ck_billing_migration_account_results_fingerprint"),
        db.Index("ix_billing_migration_account_results_account", "billing_account_id", "created_at"),
    )


class BillingMigrationReview(db.Model):
    """A documented reconciliation review: the only authority for a ``legacy_unattributed`` lot (D06, D16 step 7)."""

    __tablename__ = "billing_migration_reviews"

    id = _id()
    review_key = db.Column(db.String(255), nullable=False)
    billing_account_id = _ref("fk_billing_migration_reviews_account", "billing_accounts")
    subject_user_id = _ref("fk_billing_migration_reviews_subject", "users")
    amount = db.Column(db.BigInteger, nullable=False)
    expiry_basis = db.Column(db.String(40), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    # A non-expiring review needs a real non-expiring legacy purchase of the subject with no grant of its own.
    expiry_evidence_payment_id = db.Column(db.String(36), nullable=True)
    expiry_evidence_reference = db.Column(db.String(255), nullable=False)
    candidates_json = db.Column(db.JSON, nullable=False)
    reason = db.Column(db.Text, nullable=False)
    evidence_fingerprint = db.Column(db.String(64), nullable=False)
    reviewer_user_id = _ref("fk_billing_migration_reviews_reviewer", "users")
    staff_permission_grant_id = _ref("fk_billing_migration_reviews_grant", "billing_staff_permission_grants")
    reviewed_at = db.Column(db.DateTime(timezone=True), nullable=False)
    request_fingerprint = db.Column(db.String(64), nullable=False)
    idempotency_registry_id = _ref("fk_billing_migration_reviews_registry", "idempotency_registry")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("review_key", name="uq_billing_migration_reviews_key"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_billing_migration_reviews_registry"),
        # One review per evidence: a second, conflicting approval of the same evidence is refused.
        db.UniqueConstraint("billing_account_id", "subject_user_id", "evidence_fingerprint",
                            name="uq_billing_migration_reviews_evidence"),
        db.UniqueConstraint("expiry_evidence_payment_id", name="uq_billing_migration_reviews_expiry_payment"),
        db.CheckConstraint("amount > 0", name="ck_billing_migration_reviews_amount"),
        db.CheckConstraint(
            "length(trim(expiry_evidence_reference)) > 0 AND ("
            "(expiry_basis = 'legacy_cycle_end' AND expires_at IS NOT NULL AND expiry_evidence_payment_id IS NULL) OR "
            "(expiry_basis = 'non_expiring_legacy_contract' AND expires_at IS NULL "
            "AND expiry_evidence_payment_id IS NOT NULL))",
            name="ck_billing_migration_reviews_expiry_evidence",
        ),
        db.CheckConstraint(
            "length(trim(reason)) > 0 AND " + _FINGERPRINT.format("evidence_fingerprint") + " AND "
            + _FINGERPRINT.format("request_fingerprint"),
            name="ck_billing_migration_reviews_provenance",
        ),
        db.Index("ix_billing_migration_reviews_account_subject", "billing_account_id", "subject_user_id"),
    )


class BillingMigrationOpening(db.Model):
    """One ``migration_opening`` lot: its legacy source, evidence, calculation, and exact ledger identity."""

    __tablename__ = "billing_migration_openings"

    id = _id()
    run_id = _ref("fk_billing_migration_openings_run", "billing_migration_runs")
    account_result_id = _ref("fk_billing_migration_openings_result", "billing_migration_account_results")
    billing_account_id = _ref("fk_billing_migration_openings_account", "billing_accounts")
    opening_key = db.Column(db.String(255), nullable=False)
    legacy_source_kind = db.Column(db.String(40), nullable=False)
    legacy_source_id = db.Column(db.String(255), nullable=False)
    lot_id = _ref("fk_billing_migration_openings_lot", "credit_lots", deferred=True)
    ledger_entry_id = _ref("fk_billing_migration_openings_entry", "credit_ledger_entries", deferred=True)
    idempotency_registry_id = _ref("fk_billing_migration_openings_registry", "idempotency_registry")
    lot_source_type = db.Column(db.String(40), nullable=False)
    member_attribution_id = _ref("fk_billing_migration_openings_member", "users", nullable=True)
    original_amount = db.Column(db.BigInteger, nullable=False)
    opening_amount = db.Column(db.BigInteger, nullable=False)
    available_at = db.Column(db.DateTime(timezone=True), nullable=False)
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)
    expiry_basis = db.Column(db.String(40), nullable=False)
    effective_at = db.Column(db.DateTime(timezone=True), nullable=False)
    evidence_rank = db.Column(db.Integer, nullable=False)
    source_fingerprint = db.Column(db.String(64), nullable=False)
    evidence_json = db.Column(db.JSON, nullable=False)
    review_id = _ref("fk_billing_migration_openings_review", "billing_migration_reviews", nullable=True)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("opening_key", name="uq_billing_migration_openings_key"),
        db.UniqueConstraint("lot_id", name="uq_billing_migration_openings_lot"),
        db.UniqueConstraint("ledger_entry_id", name="uq_billing_migration_openings_entry"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_billing_migration_openings_registry"),
        db.UniqueConstraint("review_id", name="uq_billing_migration_openings_review"),
        # B1: a legacy source funds at most one opening, across every billing account, forever.
        db.UniqueConstraint("legacy_source_kind", "legacy_source_id", name="uq_billing_migration_openings_source"),
        db.CheckConstraint(
            f"legacy_source_kind IN ({_quoted(LEGACY_SOURCE_KINDS)})",
            name="ck_billing_migration_openings_kind",
        ),
        db.CheckConstraint(
            f"lot_source_type IN ({_quoted(OPENING_LOT_SOURCES)})",
            name="ck_billing_migration_openings_source",
        ),
        db.CheckConstraint(
            "(legacy_source_kind IN ('user_recurring_meter', 'organization_recurring_meter') "
            "AND lot_source_type IN ('free_recurring', 'subscription_recurring') AND expires_at IS NOT NULL "
            "AND expiry_basis = 'legacy_cycle_end' AND evidence_rank = 3 AND review_id IS NULL) OR "
            "(legacy_source_kind = 'persistent_credit_grant' "
            "AND lot_source_type IN ('credit_pack_purchase', 'promotional') AND expires_at IS NULL "
            "AND expiry_basis = 'non_expiring_legacy_contract' AND evidence_rank = 1 "
            "AND review_id IS NULL AND member_attribution_id IS NOT NULL) OR "
            "(legacy_source_kind = 'reviewed_unattributed' AND lot_source_type = 'legacy_unattributed' "
            "AND evidence_rank = 6 AND review_id IS NOT NULL AND member_attribution_id IS NOT NULL "
            "AND ((expiry_basis = 'legacy_cycle_end' AND expires_at IS NOT NULL) "
            "OR (expiry_basis = 'non_expiring_legacy_contract' AND expires_at IS NULL)))",
            name="ck_billing_migration_openings_classification",
        ),
        db.CheckConstraint(
            "legacy_source_kind <> 'organization_recurring_meter' OR member_attribution_id IS NULL",
            name="ck_billing_migration_openings_pool_owner",
        ),
        db.CheckConstraint(
            "original_amount > 0 AND opening_amount > 0 AND opening_amount <= original_amount",
            name="ck_billing_migration_openings_amounts",
        ),
        db.CheckConstraint(
            "(expires_at IS NULL OR expires_at > available_at) AND available_at <= effective_at "
            "AND (expires_at IS NULL OR expires_at > effective_at)",
            name="ck_billing_migration_openings_interval",
        ),
        db.CheckConstraint(
            "length(trim(opening_key)) > 0 AND length(trim(legacy_source_id)) > 0 AND "
            + _FINGERPRINT.format("source_fingerprint"),
            name="ck_billing_migration_openings_provenance",
        ),
        db.Index("ix_billing_migration_openings_account", "billing_account_id", "run_id"),
    )


class BillingMigrationPaymentArchive(db.Model):
    """One legacy payment row preserved exactly as stored, with its evidence classification (never a transaction)."""

    __tablename__ = "billing_migration_payment_archives"

    id = _id()
    run_id = _ref("fk_billing_migration_payment_archives_run", "billing_migration_runs")
    # The legacy ``payments`` row and its links, copied as stored; no foreign keys so the archive is never constrained.
    payment_id = db.Column(db.String(36), nullable=False)
    external_reference = db.Column(db.String(255), nullable=False)
    source = db.Column(db.String(40), nullable=False)
    legacy_user_id = db.Column(db.String(36), nullable=True)
    legacy_organization_id = db.Column(db.String(36), nullable=True)
    legacy_billing_account_id = db.Column(db.String(36), nullable=True)
    currency = db.Column(db.String(8), nullable=False)
    amount_paid_cents = db.Column(db.BigInteger, nullable=False)
    amount_due_cents = db.Column(db.BigInteger, nullable=False)
    discount_cents = db.Column(db.BigInteger, nullable=False)
    is_comped = db.Column(db.Boolean, nullable=False)
    promotion_code = db.Column(db.String(120), nullable=True)
    plan_key = db.Column(db.String(40), nullable=True)
    billing_interval = db.Column(db.String(10), nullable=True)
    stripe_subscription_id = db.Column(db.String(255), nullable=True)
    # Naive, exactly like the legacy columns, so the copy compares exactly.
    paid_at = db.Column(db.DateTime, nullable=False)
    legacy_created_at = db.Column(db.DateTime, nullable=False)
    classification = db.Column(db.String(24), nullable=False)
    classification_reference = db.Column(db.String(255), nullable=True)
    # What the legacy row never recorded (processor event, tax, fees, lines, ...): listed, never filled in.
    unresolved_json = db.Column(db.JSON, nullable=False)
    evidence_fingerprint = db.Column(db.String(64), nullable=False)
    idempotency_registry_id = _ref("fk_billing_migration_payment_archives_registry", "idempotency_registry")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("payment_id", name="uq_billing_migration_payment_archives_payment"),
        db.UniqueConstraint("external_reference", name="uq_billing_migration_payment_archives_reference"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_billing_migration_payment_archives_registry"),
        db.CheckConstraint(
            f"classification IN ({_quoted(PAYMENT_CLASSIFICATIONS)})",
            name="ck_billing_migration_payment_archives_classification",
        ),
        db.CheckConstraint(
            "(classification = 'test_activity' AND legacy_user_id IS NOT NULL "
            "AND classification_reference IS NOT NULL AND length(trim(classification_reference)) > 0) OR "
            "(classification = 'unverified' AND classification_reference IS NULL)",
            name="ck_billing_migration_payment_archives_basis",
        ),
        db.CheckConstraint(
            "length(trim(payment_id)) > 0 AND length(trim(external_reference)) > 0 AND length(trim(source)) > 0 "
            "AND amount_paid_cents >= 0 AND amount_due_cents >= 0 AND discount_cents >= 0 AND "
            + _FINGERPRINT.format("evidence_fingerprint"),
            name="ck_billing_migration_payment_archives_shape",
        ),
        db.Index("ix_billing_migration_payment_archives_user", "legacy_user_id"),
    )


class BillingMigrationPlanMapping(db.Model):
    """The evidence-backed legacy plan, subscription, entitlements, and seats of one established account in one run."""

    __tablename__ = "billing_migration_plan_mappings"

    id = _id()
    run_id = _ref("fk_billing_migration_plan_mappings_run", "billing_migration_runs")
    establishment_id = _ref("fk_billing_migration_plan_mappings_establishment", "billing_migration_establishments")
    billing_account_id = _ref("fk_billing_migration_plan_mappings_account", "billing_accounts")
    organization_id = _ref("fk_billing_migration_plan_mappings_organization", "organizations")
    outcome = db.Column(db.String(32), nullable=False)
    # The organization's legacy plan (its owner's plan, the legacy rule); NULL only when quarantined.
    legacy_plan_key = db.Column(db.String(50), nullable=True)
    snapshot_at = db.Column(db.DateTime(timezone=True), nullable=False)
    mapping_json = db.Column(db.JSON, nullable=False)
    unresolved_json = db.Column(db.JSON, nullable=False)
    quarantine_codes_json = db.Column(db.JSON, nullable=False)
    evidence_fingerprint = db.Column(db.String(64), nullable=False)
    idempotency_registry_id = _ref("fk_billing_migration_plan_mappings_registry", "idempotency_registry")
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, default=_now, server_default=db.func.now())

    __table_args__ = (
        db.UniqueConstraint("run_id", "billing_account_id", name="uq_billing_migration_plan_mappings_run_account"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_billing_migration_plan_mappings_registry"),
        db.CheckConstraint(
            f"outcome IN ({_quoted(PLAN_MAPPING_OUTCOMES)})",
            name="ck_billing_migration_plan_mappings_outcome",
        ),
        db.CheckConstraint(
            "outcome = 'quarantined' OR (legacy_plan_key IS NOT NULL AND length(trim(legacy_plan_key)) > 0)",
            name="ck_billing_migration_plan_mappings_plan",
        ),
        db.CheckConstraint(
            _FINGERPRINT.format("evidence_fingerprint"),
            name="ck_billing_migration_plan_mappings_fingerprint",
        ),
        db.Index("ix_billing_migration_plan_mappings_account", "billing_account_id", "created_at"),
    )
