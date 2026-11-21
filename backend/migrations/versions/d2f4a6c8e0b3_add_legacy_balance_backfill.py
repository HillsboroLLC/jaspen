"""Phase 14: evidence-backed legacy backfill (inactive).

Adds nine immutable evidence tables (D16 step 1, ownership and payers; steps
6-8, opening balances; lifecycle D06 ``migration_opening`` and
``legacy_unattributed``; the founder-approved legacy payment archive and plan
mappings) and database guards that make Phase 14 the only path to a migration
lot, and every migration lot traceable to a real legacy row:

* an establishment names its own organization's billing account; a payer
  binding needs an established account that carries the payer's own processor
  customer, and each payer, customer, and account is bound at most once; a
  payment attribution must copy a real legacy payment of the bound payer
  exactly, and each payment is attributed at most once;
* a migration opening needs an established account and its authoritative
  legacy source: the active persistent grant (same member, original and
  remaining amounts) behind a real payment attributed to this account, with
  its original non-expiring terms; the member's or organization's live legacy
  meter (same remaining, limit, cycle start, and on PostgreSQL the cycle end);
  or an exact review never approved by the run's operator;
* each legacy source opens at most once across every billing account;
* a ``migration_opening`` ledger entry needs its Phase 14 opening row, of an
  ``opened`` account result, naming the same lot, account, registry claim,
  amount, and effective time; a migration lot is never funded by a ``grant``;
* a lot named by an opening must equal that opening exactly (account, source,
  original amount, availability, expiry, member attribution, no scope);
* a ``legacy_unattributed`` lot needs a reviewed opening: a documented
  reconciliation review by an explicit, unrevoked ``billing.migration.review``
  staff grant valid at the actual current time (READ COMMITTED), by someone
  who is not the subject, a member, owner, or bound payer of the beneficiary
  organization, for no more than the subject's legacy counter, and, when
  non-expiring, backed by a real non-expiring purchase that funds no grant;
* at commit, every opening has its lot and entry, and every opened result
  equals its openings exactly;
* a payment archive copies a real legacy payment row exactly (every column,
  as stored) under its own claim, and each payment is archived at most once;
  ``test_activity`` needs a named payer and an attestation reference; no row
  is a financial transaction and nothing missing is filled in;
* a plan mapping names an established billing account of its own
  organization under its own claim.

Four earlier lot guards (Phase 6 recurring lot and its deferred final check,
Phase 9 purchased lot, Phase 10 offer lot) receive one exact, asserted early
return for a lot that matches its Phase 14 opening; the opening itself can
only exist with the legacy evidence above, so the early return never skips
substantive funding evidence. Every other lot is judged by the unchanged
earlier rule. The patch reads each live guard body and replaces exactly one
anchor, so the rest stays byte-identical, and downgrade removes exactly what
upgrade inserted. The staff-permission CHECK gains the review permission (no
holder is defined).

Activation prerequisite (not created here): only a dedicated migration
database role may write the Phase 14 tables; the runtime role may not.

No row is created by the migration. Downgrade refuses while any Phase 14 row
or review-permission grant exists.

Revision ID: d2f4a6c8e0b3
Revises: c8e0a2b4d6f1
"""

from importlib import import_module

from alembic import op
import sqlalchemy as sa


revision = "d2f4a6c8e0b3"
down_revision = "c8e0a2b4d6f1"
branch_labels = None
depends_on = None


# Children first (drop order).
TABLES = (
    "billing_migration_plan_mappings", "billing_migration_payment_archives", "billing_migration_openings", "billing_migration_reviews", "billing_migration_account_results",
    "billing_migration_payment_attributions", "billing_migration_payer_bindings",
    "billing_migration_establishments", "billing_migration_runs",
)
REVIEW_PERMISSION = "'billing.migration.review'"
PERMISSION_CHECK = (
    "billing_staff_permission_grants", "ck_billing_staff_permission_grants_permission",
    "permission IN ('billing.comp.grant', 'billing.internal_funding.grant', 'billing.enterprise_contract.manage')",
    "permission IN ('billing.comp.grant', 'billing.internal_funding.grant', 'billing.enterprise_contract.manage', "
    "'billing.migration.review')",
)


class Phase14EvidenceNotEmptyError(RuntimeError):
    """Downgrade refuses to discard migration evidence or a review-permission grant."""


def _phase11():
    return import_module("migrations.versions.b4d6f8a0c2e5_add_enterprise_contracts_and_term_credit_expiry")


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def _id():
    return sa.Column("id", sa.String(36), primary_key=True)


def _ref(name, table, constraint, *, nullable=False, deferred=False):
    options = {"deferrable": True, "initially": "DEFERRED"} if deferred else {}
    return sa.Column(name, sa.String(36), sa.ForeignKey(f"{table}.id", name=constraint, ondelete="RESTRICT",
                                                        **options), nullable=nullable)


def _ts(name, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _created():
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


# Literal copies of the model CHECK constraints: a revision never reads live models.
CHECKS = {
    'BillingMigrationRun': (
        ("algorithm_version = 'jaspen.billing.migration.v1' AND credit_unit_basis = 'jaspen.legacy_internal_unit.v1' AND units_per_displayed_credit = 1000",
         'ck_billing_migration_runs_basis'),
        ("actor_type = 'system' AND length(trim(actor_id)) > 0 AND length(trim(run_key)) > 0 AND length(trim(authorization_reference)) > 0 AND length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint)",
         'ck_billing_migration_runs_provenance'),
        ("expiry_policy = 'original_terms'",
         'ck_billing_migration_runs_policy'),
    ),
    'BillingMigrationEstablishment': (
        ('length(evidence_fingerprint) = 64 AND evidence_fingerprint = lower(evidence_fingerprint)',
         'ck_billing_migration_establishments_fingerprint'),
        ("(outcome IN ('established', 'unchanged') AND billing_account_id IS NOT NULL) OR (outcome = 'quarantined' AND NOT account_created)",
         'ck_billing_migration_establishments_shape'),
        ("outcome = 'established' OR NOT account_created",
         'ck_billing_migration_establishments_created'),
        ("outcome IN ('established', 'unchanged', 'quarantined')",
         'ck_billing_migration_establishments_outcome'),
    ),
    'BillingMigrationPayerBinding': (
        ("processor = 'stripe' AND length(trim(processor_customer_id)) > 0",
         'ck_billing_migration_payer_bindings_identity'),
    ),
    'BillingMigrationPaymentAttribution': (
        ('length(trim(payment_id)) > 0 AND length(trim(external_reference)) > 0 AND length(trim(source)) > 0 AND amount_paid_cents >= 0 AND amount_due_cents >= 0 AND discount_cents >= 0',
         'ck_billing_migration_payment_attributions_shape'),
    ),
    'BillingMigrationAccountResult': (
        ('length(evidence_fingerprint) = 64 AND evidence_fingerprint = lower(evidence_fingerprint)',
         'ck_billing_migration_account_results_fingerprint'),
        ("(outcome = 'opened' AND opened_count > 0 AND opened_total > 0) OR (outcome <> 'opened' AND opened_count = 0 AND opened_total = 0)",
         'ck_billing_migration_account_results_opened'),
        ("(outcome <> 'quarantined' OR NOT credit_reconciled) AND (NOT cutover_eligible OR credit_reconciled)",
         'ck_billing_migration_account_results_eligibility'),
        ("outcome IN ('opened', 'unchanged', 'quarantined')",
         'ck_billing_migration_account_results_outcome'),
    ),
    'BillingMigrationReview': (
        ('amount > 0',
         'ck_billing_migration_reviews_amount'),
        ("length(trim(expiry_evidence_reference)) > 0 AND ((expiry_basis = 'legacy_cycle_end' AND expires_at IS NOT NULL AND expiry_evidence_payment_id IS NULL) OR (expiry_basis = 'non_expiring_legacy_contract' AND expires_at IS NULL AND expiry_evidence_payment_id IS NOT NULL))",
         'ck_billing_migration_reviews_expiry_evidence'),
        ('length(trim(reason)) > 0 AND length(evidence_fingerprint) = 64 AND evidence_fingerprint = lower(evidence_fingerprint) AND length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint)',
         'ck_billing_migration_reviews_provenance'),
    ),
    'BillingMigrationOpening': (
        ("(legacy_source_kind IN ('user_recurring_meter', 'organization_recurring_meter') AND lot_source_type IN ('free_recurring', 'subscription_recurring') AND expires_at IS NOT NULL AND expiry_basis = 'legacy_cycle_end' AND evidence_rank = 3 AND review_id IS NULL) OR (legacy_source_kind = 'persistent_credit_grant' AND lot_source_type IN ('credit_pack_purchase', 'promotional') AND expires_at IS NULL AND expiry_basis = 'non_expiring_legacy_contract' AND evidence_rank = 1 AND review_id IS NULL AND member_attribution_id IS NOT NULL) OR (legacy_source_kind = 'reviewed_unattributed' AND lot_source_type = 'legacy_unattributed' AND evidence_rank = 6 AND review_id IS NOT NULL AND member_attribution_id IS NOT NULL AND ((expiry_basis = 'legacy_cycle_end' AND expires_at IS NOT NULL) OR (expiry_basis = 'non_expiring_legacy_contract' AND expires_at IS NULL)))",
         'ck_billing_migration_openings_classification'),
        ("legacy_source_kind <> 'organization_recurring_meter' OR member_attribution_id IS NULL",
         'ck_billing_migration_openings_pool_owner'),
        ('original_amount > 0 AND opening_amount > 0 AND opening_amount <= original_amount',
         'ck_billing_migration_openings_amounts'),
        ('(expires_at IS NULL OR expires_at > available_at) AND available_at <= effective_at AND (expires_at IS NULL OR expires_at > effective_at)',
         'ck_billing_migration_openings_interval'),
        ('length(trim(opening_key)) > 0 AND length(trim(legacy_source_id)) > 0 AND length(source_fingerprint) = 64 AND source_fingerprint = lower(source_fingerprint)',
         'ck_billing_migration_openings_provenance'),
        ("legacy_source_kind IN ('user_recurring_meter', 'organization_recurring_meter', 'persistent_credit_grant', 'reviewed_unattributed')",
         'ck_billing_migration_openings_kind'),
        ("lot_source_type IN ('free_recurring', 'subscription_recurring', 'credit_pack_purchase', 'promotional', 'legacy_unattributed')",
         'ck_billing_migration_openings_source'),
    ),
    'BillingMigrationPaymentArchive': (
        ("classification IN ('test_activity', 'unverified')",
         'ck_billing_migration_payment_archives_classification'),
        ("(classification = 'test_activity' AND legacy_user_id IS NOT NULL AND classification_reference IS NOT NULL AND length(trim(classification_reference)) > 0) OR (classification = 'unverified' AND classification_reference IS NULL)",
         'ck_billing_migration_payment_archives_basis'),
        ('length(trim(payment_id)) > 0 AND length(trim(external_reference)) > 0 AND length(trim(source)) > 0 AND amount_paid_cents >= 0 AND amount_due_cents >= 0 AND discount_cents >= 0 AND length(evidence_fingerprint) = 64 AND evidence_fingerprint = lower(evidence_fingerprint)',
         'ck_billing_migration_payment_archives_shape'),
    ),
    'BillingMigrationPlanMapping': (
        ('length(evidence_fingerprint) = 64 AND evidence_fingerprint = lower(evidence_fingerprint)',
         'ck_billing_migration_plan_mappings_fingerprint'),
        ("outcome IN ('mapped', 'mapped_pending_processor', 'quarantined')",
         'ck_billing_migration_plan_mappings_outcome'),
        ("outcome = 'quarantined' OR (legacy_plan_key IS NOT NULL AND length(trim(legacy_plan_key)) > 0)",
         'ck_billing_migration_plan_mappings_plan'),
    ),
}


def _checks(model):
    return [sa.CheckConstraint(text, name=name) for text, name in CHECKS[model]]


def _create_tables():
    op.create_table(
        "billing_migration_runs",
        _id(),
        sa.Column("run_key", sa.String(128), nullable=False),
        sa.Column("algorithm_version", sa.String(64), nullable=False),
        sa.Column("credit_unit_basis", sa.String(64), nullable=False),
        sa.Column("units_per_displayed_credit", sa.Integer(), nullable=False),
        sa.Column("expiry_policy", sa.String(40), nullable=False),
        sa.Column("authorization_reference", sa.String(255), nullable=False),
        sa.Column("actor_type", sa.String(40), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        _ref("operator_user_id", "users", "fk_billing_migration_runs_operator"),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        _ref("idempotency_registry_id", "idempotency_registry", "fk_billing_migration_runs_registry"),
        _ts("started_at"),
        _created(),
        sa.UniqueConstraint("run_key", name="uq_billing_migration_runs_key"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_billing_migration_runs_registry"),
        *_checks("BillingMigrationRun"),
    )
    op.create_table(
        "billing_migration_establishments",
        _id(),
        _ref("run_id", "billing_migration_runs", "fk_billing_migration_establishments_run"),
        _ref("organization_id", "organizations", "fk_billing_migration_establishments_organization"),
        _ref("billing_account_id", "billing_accounts", "fk_billing_migration_establishments_account", nullable=True),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("account_created", sa.Boolean(), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(64), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("quarantine_codes_json", sa.JSON(), nullable=False),
        _ref("idempotency_registry_id", "idempotency_registry", "fk_billing_migration_establishments_registry"),
        _created(),
        sa.UniqueConstraint("run_id", "organization_id", name="uq_billing_migration_establishments_run_org"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_billing_migration_establishments_registry"),
        *_checks("BillingMigrationEstablishment"),
    )
    op.create_index("ix_billing_migration_establishments_org", "billing_migration_establishments",
                    ["organization_id", "created_at"])
    op.create_index("ix_billing_migration_establishments_account", "billing_migration_establishments",
                    ["billing_account_id"])
    op.create_table(
        "billing_migration_payer_bindings",
        _id(),
        _ref("establishment_id", "billing_migration_establishments",
             "fk_billing_migration_payer_bindings_establishment"),
        _ref("billing_account_id", "billing_accounts", "fk_billing_migration_payer_bindings_account"),
        _ref("payer_user_id", "users", "fk_billing_migration_payer_bindings_payer"),
        sa.Column("processor", sa.String(32), nullable=False),
        sa.Column("processor_customer_id", sa.String(255), nullable=False),
        sa.Column("customer_assigned_by_migration", sa.Boolean(), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        _created(),
        sa.UniqueConstraint("payer_user_id", name="uq_billing_migration_payer_bindings_payer"),
        sa.UniqueConstraint("processor", "processor_customer_id", name="uq_billing_migration_payer_bindings_customer"),
        sa.UniqueConstraint("billing_account_id", name="uq_billing_migration_payer_bindings_account"),
        *_checks("BillingMigrationPayerBinding"),
    )
    op.create_table(
        "billing_migration_payment_attributions",
        _id(),
        _ref("establishment_id", "billing_migration_establishments",
             "fk_billing_migration_payment_attributions_establishment"),
        _ref("payer_binding_id", "billing_migration_payer_bindings",
             "fk_billing_migration_payment_attributions_binding"),
        _ref("billing_account_id", "billing_accounts", "fk_billing_migration_payment_attributions_account"),
        sa.Column("payment_id", sa.String(36), nullable=False),
        sa.Column("external_reference", sa.String(255), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("amount_paid_cents", sa.BigInteger(), nullable=False),
        sa.Column("amount_due_cents", sa.BigInteger(), nullable=False),
        sa.Column("discount_cents", sa.BigInteger(), nullable=False),
        sa.Column("is_comped", sa.Boolean(), nullable=False),
        _created(),
        sa.UniqueConstraint("payment_id", name="uq_billing_migration_payment_attributions_payment"),
        sa.UniqueConstraint("external_reference", name="uq_billing_migration_payment_attributions_reference"),
        *_checks("BillingMigrationPaymentAttribution"),
    )
    op.create_index("ix_billing_migration_payment_attributions_account", "billing_migration_payment_attributions",
                    ["billing_account_id"])
    op.create_table(
        "billing_migration_account_results",
        _id(),
        _ref("run_id", "billing_migration_runs", "fk_billing_migration_account_results_run"),
        _ref("billing_account_id", "billing_accounts", "fk_billing_migration_account_results_account"),
        _ref("organization_id", "organizations", "fk_billing_migration_account_results_organization"),
        sa.Column("outcome", sa.String(24), nullable=False),
        _ts("snapshot_at"),
        sa.Column("evidence_fingerprint", sa.String(64), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("quarantine_codes_json", sa.JSON(), nullable=False),
        sa.Column("conservation_json", sa.JSON(), nullable=False),
        sa.Column("comparison_json", sa.JSON(), nullable=False),
        sa.Column("opened_count", sa.Integer(), nullable=False),
        sa.Column("opened_total", sa.BigInteger(), nullable=False),
        sa.Column("credit_reconciled", sa.Boolean(), nullable=False),
        sa.Column("cutover_eligible", sa.Boolean(), nullable=False),
        _ref("idempotency_registry_id", "idempotency_registry", "fk_billing_migration_account_results_registry"),
        _created(),
        sa.UniqueConstraint("run_id", "billing_account_id", name="uq_billing_migration_account_results_run_account"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_billing_migration_account_results_registry"),
        *_checks("BillingMigrationAccountResult"),
    )
    op.create_index("ix_billing_migration_account_results_account", "billing_migration_account_results",
                    ["billing_account_id", "created_at"])
    op.create_table(
        "billing_migration_reviews",
        _id(),
        sa.Column("review_key", sa.String(255), nullable=False),
        _ref("billing_account_id", "billing_accounts", "fk_billing_migration_reviews_account"),
        _ref("subject_user_id", "users", "fk_billing_migration_reviews_subject"),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("expiry_basis", sa.String(40), nullable=False),
        _ts("expires_at", nullable=True),
        sa.Column("expiry_evidence_payment_id", sa.String(36), nullable=True),
        sa.Column("expiry_evidence_reference", sa.String(255), nullable=False),
        sa.Column("candidates_json", sa.JSON(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(64), nullable=False),
        _ref("reviewer_user_id", "users", "fk_billing_migration_reviews_reviewer"),
        _ref("staff_permission_grant_id", "billing_staff_permission_grants", "fk_billing_migration_reviews_grant"),
        _ts("reviewed_at"),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        _ref("idempotency_registry_id", "idempotency_registry", "fk_billing_migration_reviews_registry"),
        _created(),
        sa.UniqueConstraint("review_key", name="uq_billing_migration_reviews_key"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_billing_migration_reviews_registry"),
        sa.UniqueConstraint("billing_account_id", "subject_user_id", "evidence_fingerprint",
                            name="uq_billing_migration_reviews_evidence"),
        sa.UniqueConstraint("expiry_evidence_payment_id", name="uq_billing_migration_reviews_expiry_payment"),
        *_checks("BillingMigrationReview"),
    )
    op.create_index("ix_billing_migration_reviews_account_subject", "billing_migration_reviews",
                    ["billing_account_id", "subject_user_id"])
    op.create_table(
        "billing_migration_openings",
        _id(),
        _ref("run_id", "billing_migration_runs", "fk_billing_migration_openings_run"),
        _ref("account_result_id", "billing_migration_account_results", "fk_billing_migration_openings_result"),
        _ref("billing_account_id", "billing_accounts", "fk_billing_migration_openings_account"),
        sa.Column("opening_key", sa.String(255), nullable=False),
        sa.Column("legacy_source_kind", sa.String(40), nullable=False),
        sa.Column("legacy_source_id", sa.String(255), nullable=False),
        _ref("lot_id", "credit_lots", "fk_billing_migration_openings_lot", deferred=True),
        _ref("ledger_entry_id", "credit_ledger_entries", "fk_billing_migration_openings_entry", deferred=True),
        _ref("idempotency_registry_id", "idempotency_registry", "fk_billing_migration_openings_registry"),
        sa.Column("lot_source_type", sa.String(40), nullable=False),
        _ref("member_attribution_id", "users", "fk_billing_migration_openings_member", nullable=True),
        sa.Column("original_amount", sa.BigInteger(), nullable=False),
        sa.Column("opening_amount", sa.BigInteger(), nullable=False),
        _ts("available_at"),
        _ts("expires_at", nullable=True),
        sa.Column("expiry_basis", sa.String(40), nullable=False),
        _ts("effective_at"),
        sa.Column("evidence_rank", sa.Integer(), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        _ref("review_id", "billing_migration_reviews", "fk_billing_migration_openings_review", nullable=True),
        _created(),
        sa.UniqueConstraint("opening_key", name="uq_billing_migration_openings_key"),
        sa.UniqueConstraint("lot_id", name="uq_billing_migration_openings_lot"),
        sa.UniqueConstraint("ledger_entry_id", name="uq_billing_migration_openings_entry"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_billing_migration_openings_registry"),
        sa.UniqueConstraint("review_id", name="uq_billing_migration_openings_review"),
        sa.UniqueConstraint("legacy_source_kind", "legacy_source_id", name="uq_billing_migration_openings_source"),
        *_checks("BillingMigrationOpening"),
    )
    op.create_index("ix_billing_migration_openings_account", "billing_migration_openings",
                    ["billing_account_id", "run_id"])
    op.create_table(
        "billing_migration_payment_archives",
        _id(),
        _ref("run_id", "billing_migration_runs", "fk_billing_migration_payment_archives_run"),
        sa.Column("payment_id", sa.String(36), nullable=False),
        sa.Column("external_reference", sa.String(255), nullable=False),
        sa.Column("source", sa.String(40), nullable=False),
        sa.Column("legacy_user_id", sa.String(36), nullable=True),
        sa.Column("legacy_organization_id", sa.String(36), nullable=True),
        sa.Column("legacy_billing_account_id", sa.String(36), nullable=True),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("amount_paid_cents", sa.BigInteger(), nullable=False),
        sa.Column("amount_due_cents", sa.BigInteger(), nullable=False),
        sa.Column("discount_cents", sa.BigInteger(), nullable=False),
        sa.Column("is_comped", sa.Boolean(), nullable=False),
        sa.Column("promotion_code", sa.String(120), nullable=True),
        sa.Column("plan_key", sa.String(40), nullable=True),
        sa.Column("billing_interval", sa.String(10), nullable=True),
        sa.Column("stripe_subscription_id", sa.String(255), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=False),
        sa.Column("legacy_created_at", sa.DateTime(), nullable=False),
        sa.Column("classification", sa.String(24), nullable=False),
        sa.Column("classification_reference", sa.String(255), nullable=True),
        sa.Column("unresolved_json", sa.JSON(), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(64), nullable=False),
        _ref("idempotency_registry_id", "idempotency_registry", "fk_billing_migration_payment_archives_registry"),
        _created(),
        sa.UniqueConstraint("payment_id", name="uq_billing_migration_payment_archives_payment"),
        sa.UniqueConstraint("external_reference", name="uq_billing_migration_payment_archives_reference"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_billing_migration_payment_archives_registry"),
        *_checks("BillingMigrationPaymentArchive"),
    )
    op.create_index("ix_billing_migration_payment_archives_user", "billing_migration_payment_archives",
                    ["legacy_user_id"])
    op.create_table(
        "billing_migration_plan_mappings",
        _id(),
        _ref("run_id", "billing_migration_runs", "fk_billing_migration_plan_mappings_run"),
        _ref("establishment_id", "billing_migration_establishments", "fk_billing_migration_plan_mappings_establishment"),
        _ref("billing_account_id", "billing_accounts", "fk_billing_migration_plan_mappings_account"),
        _ref("organization_id", "organizations", "fk_billing_migration_plan_mappings_organization"),
        sa.Column("outcome", sa.String(32), nullable=False),
        sa.Column("legacy_plan_key", sa.String(50), nullable=True),
        _ts("snapshot_at"),
        sa.Column("mapping_json", sa.JSON(), nullable=False),
        sa.Column("unresolved_json", sa.JSON(), nullable=False),
        sa.Column("quarantine_codes_json", sa.JSON(), nullable=False),
        sa.Column("evidence_fingerprint", sa.String(64), nullable=False),
        _ref("idempotency_registry_id", "idempotency_registry", "fk_billing_migration_plan_mappings_registry"),
        _created(),
        sa.UniqueConstraint("run_id", "billing_account_id", name="uq_billing_migration_plan_mappings_run_account"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_billing_migration_plan_mappings_registry"),
        *_checks("BillingMigrationPlanMapping"),
    )
    op.create_index("ix_billing_migration_plan_mappings_account", "billing_migration_plan_mappings",
                    ["billing_account_id", "created_at"])


# ---------------------------------------------------------------------------
# Earlier lot guards: one exact early return for a lot that matches its opening
# ---------------------------------------------------------------------------

PG_BYPASS = " IF phase14_is_opening_lot({row}) THEN RETURN NEW; END IF;"
PG_PATCHES = (
    ("phase6_recurring_lot_guard",
     "IF NEW.source_type NOT IN ('free_recurring','subscription_recurring') THEN RETURN NEW; END IF;", "NEW"),
    ("phase6_recurring_effect_final_guard",
     "IF lot_row.source_type NOT IN ('free_recurring','subscription_recurring') THEN RETURN NEW; END IF;",
     "lot_row"),
    ("phase9_purchase_lot_guard", "IF NEW.source_type<>'credit_pack_purchase' THEN RETURN NEW; END IF;", "NEW"),
    ("phase10_offer_lot_guard",
     "IF NEW.source_type NOT IN ('trial','promotional','comp','internal') THEN RETURN NEW; END IF;", "NEW"),
)

SQLITE_OPENING_MATCH = (
    "EXISTS (SELECT 1 FROM billing_migration_openings m WHERE m.id=NEW.source_id AND m.lot_id=NEW.id "
    "AND m.billing_account_id=NEW.billing_account_id AND m.lot_source_type=NEW.source_type "
    "AND m.original_amount=NEW.original_amount AND julianday(m.available_at)=julianday(NEW.available_at) "
    "AND ((m.expires_at IS NULL AND NEW.expires_at IS NULL) OR julianday(m.expires_at)=julianday(NEW.expires_at)) "
    "AND m.member_attribution_id IS NEW.member_attribution_id AND NEW.eligibility_scope IS NULL)"
)
SQLITE_BYPASS = f" AND NOT {SQLITE_OPENING_MATCH}"
SQLITE_PATCHES = (
    ("trg_phase6_recurring_lot_insert", "WHEN NEW.source_type IN ('free_recurring','subscription_recurring')"),
    ("trg_phase9_purchase_lot_insert", "WHEN NEW.source_type='credit_pack_purchase'"),
    ("trg_phase10_offer_lot_insert", "WHEN NEW.source_type IN ('trial','promotional','comp','internal')"),
)


def _replace_once(text, old, new, what):
    if text.count(old) != 1:
        raise RuntimeError(f"{what} is not in the form this revision expects")
    return text.replace(old, new)


def _pg_body(bind, name):
    rows = bind.execute(sa.text("SELECT prosrc FROM pg_proc WHERE proname=:name AND pronamespace = current_schema()::regnamespace"), {"name": name}).scalars().all()
    if len(rows) != 1:
        raise RuntimeError(f"guard function {name} was not found exactly once")
    return rows[0]


def _pg_define(name, body):
    if "$phase14$" in body:
        raise RuntimeError(f"guard function {name} cannot be quoted")
    op.execute(f"CREATE OR REPLACE FUNCTION {name}() RETURNS trigger AS $phase14${body}$phase14$ LANGUAGE plpgsql")


def _pg_patch_earlier_guards(forward):
    bind = op.get_bind()
    for name, anchor, row in PG_PATCHES:
        patched = anchor + PG_BYPASS.format(row=row)
        old, new = (anchor, patched) if forward else (patched, anchor)
        _pg_define(name, _replace_once(_pg_body(bind, name), old, new, f"guard function {name}"))


def _sqlite_patch_earlier_guards(forward):
    bind = op.get_bind()
    for name, anchor in SQLITE_PATCHES:
        sql = bind.execute(sa.text("SELECT sql FROM sqlite_master WHERE type='trigger' AND name=:name"),
                           {"name": name}).scalar_one_or_none()
        if sql is None:
            raise RuntimeError(f"trigger {name} was not found")
        old, new = (anchor, anchor + SQLITE_BYPASS) if forward else (anchor + SQLITE_BYPASS, anchor)
        sql = _replace_once(sql, old, new, f"trigger {name}")
        op.execute(f"DROP TRIGGER {name}")
        op.execute(sql)


# ---------------------------------------------------------------------------
# Phase 14 guards
# ---------------------------------------------------------------------------

# Legacy persistent-grant sources sold non-expiring, their grant reference prefixes and payment sources.
GRANT_PREFIX_SQL = ("CASE {g}.source WHEN 'credit_pack' THEN 'credit-pack:' "
                    "WHEN '300k_limited_time' THEN '300k-limited-time-credit:' END")
PAYMENT_SOURCE_SQL = ("CASE {g}.source WHEN 'credit_pack' THEN 'credit_pack' "
                      "WHEN '300k_limited_time' THEN 'limited_time_300k' END")
BENEFICIARY_SQL = (
    "({reviewer}=(SELECT o.owner_user_id FROM organizations o WHERE o.id={org}) "
    "OR EXISTS (SELECT 1 FROM organization_members om WHERE om.organization_id={org} AND om.user_id={reviewer}) "
    "OR EXISTS (SELECT 1 FROM billing_migration_payer_bindings pb WHERE pb.billing_account_id={account} "
    "AND pb.payer_user_id={reviewer}))"
)
ORPHAN_PURCHASE_SQL = (
    "EXISTS (SELECT 1 FROM payments p JOIN billing_migration_payment_attributions pa ON pa.payment_id=p.id "
    "AND pa.billing_account_id={account} WHERE p.id={payment} AND p.user_id={subject} "
    "AND p.source IN ('credit_pack','limited_time_300k') AND NOT EXISTS (SELECT 1 FROM persistent_credit_grants g "
    "WHERE g.external_reference IN ('credit-pack:'||p.external_reference, "
    "'300k-limited-time-credit:'||p.external_reference)))"
)
GRANT_SOURCE_SQL = (
    "EXISTS (SELECT 1 FROM persistent_credit_grants g JOIN payments p ON p.user_id=g.user_id "
    f"AND g.external_reference={GRANT_PREFIX_SQL.format(g='g')}||p.external_reference "
    "JOIN billing_migration_payment_attributions pa ON pa.payment_id=p.id AND pa.billing_account_id={o}.billing_account_id "
    "WHERE g.id={o}.legacy_source_id AND g.user_id={o}.member_attribution_id AND g.status='active' "
    "AND g.source IN ('credit_pack','300k_limited_time') AND g.original_amount={o}.original_amount "
    "AND g.remaining_amount={o}.opening_amount AND {o}.expires_at IS NULL "
    f"AND {{o}}.expiry_basis='non_expiring_legacy_contract' AND p.source={PAYMENT_SOURCE_SQL.format(g='g')} "
    "AND (({o}.lot_source_type='credit_pack_purchase' AND p.amount_paid_cents>0 AND NOT p.is_comped) "
    "OR ({o}.lot_source_type='promotional' AND p.amount_paid_cents=0 AND p.is_comped)))"
)

# A payment archive copies every legacy column as stored (null-safe on both dialects via {same}).
ARCHIVE_COPY_SQL = (
    "EXISTS (SELECT 1 FROM payments p WHERE p.id={n}.payment_id AND p.external_reference={n}.external_reference "
    "AND p.source={n}.source AND p.user_id {same} {n}.legacy_user_id "
    "AND p.organization_id {same} {n}.legacy_organization_id "
    "AND p.billing_account_id {same} {n}.legacy_billing_account_id AND p.currency={n}.currency "
    "AND p.amount_paid_cents={n}.amount_paid_cents AND p.amount_due_cents={n}.amount_due_cents "
    "AND p.discount_cents={n}.discount_cents AND p.is_comped={n}.is_comped "
    "AND p.promotion_code {same} {n}.promotion_code AND p.plan_key {same} {n}.plan_key "
    "AND p.billing_interval {same} {n}.billing_interval "
    "AND p.stripe_subscription_id {same} {n}.stripe_subscription_id "
    "AND p.paid_at={n}.paid_at AND p.created_at={n}.legacy_created_at)"
)
ARCHIVE_CLAIM_SQL = ("EXISTS (SELECT 1 FROM idempotency_registry g WHERE g.id={n}.idempotency_registry_id "
                     "AND g.namespace='billing.migration.payment_archive' AND g.key={n}.payment_id)")
MAPPING_ESTABLISHED_SQL = (
    "EXISTS (SELECT 1 FROM billing_migration_establishments e WHERE e.id={n}.establishment_id "
    "AND e.outcome IN ('established', 'unchanged') AND e.billing_account_id={n}.billing_account_id "
    "AND e.organization_id={n}.organization_id)"
)
MAPPING_CLAIM_SQL = ("EXISTS (SELECT 1 FROM idempotency_registry g WHERE g.id={n}.idempotency_registry_id "
                     "AND g.namespace='billing.migration.plan_mapping' "
                     "AND g.key={n}.run_id||':'||{n}.billing_account_id)")

PG_FUNCTIONS = (
    ("phase14_is_opening_lot", "credit_lots"), ("phase14_review_grant_ok", "text, text"),
    ("phase14_meter_ok", "jsonb, bigint, bigint, timestamptz, timestamptz"),
    ("phase14_lot_guard", ""), ("phase14_entry_guard", ""), ("phase14_opening_guard", ""),
    ("phase14_opening_final", ""), ("phase14_result_final", ""), ("phase14_review_guard", ""),
    ("phase14_establishment_guard", ""), ("phase14_payer_binding_guard", ""),
    ("phase14_payment_attribution_guard", ""), ("phase14_payment_archive_guard", ""),
    ("phase14_plan_mapping_guard", ""),
    ("phase14_reject_row_change", ""), ("phase14_reject_truncate", ""),
)
PG_TRIGGERS = (
    ("trg_phase14_lot_guard", "credit_lots"),
    ("trg_phase14_entry_guard", "credit_ledger_entries"),
    ("trg_phase14_opening_guard", "billing_migration_openings"),
    ("trg_phase14_opening_final", "billing_migration_openings"),
    ("trg_phase14_result_final", "billing_migration_account_results"),
    ("trg_phase14_review_guard", "billing_migration_reviews"),
    ("trg_phase14_establishment_guard", "billing_migration_establishments"),
    ("trg_phase14_payer_binding_guard", "billing_migration_payer_bindings"),
    ("trg_phase14_payment_attribution_guard", "billing_migration_payment_attributions"),
    ("trg_phase14_payment_archive_guard", "billing_migration_payment_archives"),
    ("trg_phase14_plan_mapping_guard", "billing_migration_plan_mappings"),
) + tuple((f"trg_phase14_{table}_immutable", table) for table in TABLES) \
  + tuple((f"trg_phase14_{table}_truncate", table) for table in TABLES)


def _pg_guards():
    statements = ["""
CREATE FUNCTION phase14_is_opening_lot(lot credit_lots) RETURNS boolean AS $$
  SELECT EXISTS (SELECT 1 FROM billing_migration_openings m
    WHERE m.id=lot.source_id AND m.lot_id=lot.id AND m.billing_account_id=lot.billing_account_id
      AND m.lot_source_type=lot.source_type AND m.original_amount=lot.original_amount
      AND m.available_at=lot.available_at AND m.expires_at IS NOT DISTINCT FROM lot.expires_at
      AND m.member_attribution_id IS NOT DISTINCT FROM lot.member_attribution_id
      AND lot.eligibility_scope IS NULL);
$$ LANGUAGE sql STABLE""", f"""
CREATE FUNCTION phase14_review_grant_ok(p_grant text, p_user text) RETURNS boolean AS $$
  SELECT p_grant IS NOT NULL AND p_user IS NOT NULL AND EXISTS (
    SELECT 1 FROM billing_staff_permission_grants g
    WHERE g.id=p_grant AND g.user_id=p_user AND g.permission={REVIEW_PERMISSION} AND g.permission_version=1
      AND g.starts_at<=now() AND (g.ends_at IS NULL OR g.ends_at>clock_timestamp())
      AND NOT EXISTS (SELECT 1 FROM billing_staff_permission_revocations r WHERE r.grant_id=g.id));
$$ LANGUAGE sql STABLE""", r"""
CREATE FUNCTION phase14_meter_ok(c jsonb, p_amount bigint, p_original bigint, p_start timestamptz,
                                 p_end timestamptz) RETURNS boolean AS $$
  SELECT CASE WHEN c->'thinking_power'->>'remaining' ~ '^[0-9]+$'
               AND c->'thinking_power'->>'cycle_limit' ~ '^[0-9]+$'
               AND COALESCE(c->'thinking_power'->>'overage_tokens', '0') ~ '^0+$'
               AND c->'thinking_power'->>'cycle_reset_at'
                   ~ '^[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9:.]+(Z|[+-]00:00)?$'
    THEN (c->'thinking_power'->>'remaining')::bigint=p_amount
     AND (c->'thinking_power'->>'cycle_limit')::bigint=p_original
     AND (regexp_replace(c->'thinking_power'->>'cycle_reset_at', '(Z|[+-]00:00)$', '')::timestamp
          AT TIME ZONE 'UTC')=p_start
     AND ((regexp_replace(c->'thinking_power'->>'cycle_reset_at', '(Z|[+-]00:00)$', '')::timestamp
           + interval '1 month') AT TIME ZONE 'UTC')=p_end
    ELSE false END;
$$ LANGUAGE sql IMMUTABLE""", """
CREATE FUNCTION phase14_lot_guard() RETURNS trigger AS $$
BEGIN
  IF phase14_is_opening_lot(NEW) THEN RETURN NEW; END IF;
  IF EXISTS (SELECT 1 FROM billing_migration_openings m WHERE m.lot_id=NEW.id
             OR (m.id=NEW.source_id AND m.billing_account_id=NEW.billing_account_id)) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='a migration lot must equal its opening evidence exactly';
  END IF;
  IF NEW.source_type='legacy_unattributed' THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='legacy_unattributed credit requires a reviewed Phase 14 migration opening';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql""", """
CREATE FUNCTION phase14_entry_guard() RETURNS trigger AS $$
BEGIN
  IF NEW.entry_type='migration_opening' THEN
    IF NOT EXISTS (SELECT 1 FROM billing_migration_openings m
        JOIN billing_migration_account_results r ON r.id=m.account_result_id
        WHERE m.ledger_entry_id=NEW.id AND m.lot_id=NEW.lot_id AND m.billing_account_id=NEW.billing_account_id
          AND m.idempotency_registry_id=NEW.idempotency_registry_id AND m.opening_amount=NEW.available_delta
          AND NEW.held_delta=0 AND m.effective_at=NEW.effective_at AND r.outcome='opened') THEN
      RAISE EXCEPTION USING ERRCODE='23514',
        MESSAGE='a migration_opening entry requires its Phase 14 opening evidence';
    END IF;
  ELSIF NEW.entry_type='grant' AND EXISTS (SELECT 1 FROM billing_migration_openings m WHERE m.lot_id=NEW.lot_id) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='a migration lot is funded only by its migration_opening entry';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql""", f"""
CREATE FUNCTION phase14_opening_guard() RETURNS trigger AS $$
DECLARE r billing_migration_account_results%ROWTYPE; v billing_migration_reviews%ROWTYPE;
        v_org text; v_operator text;
BEGIN
  SELECT * INTO r FROM billing_migration_account_results WHERE id=NEW.account_result_id;
  IF r.id IS NULL OR r.run_id<>NEW.run_id OR r.billing_account_id<>NEW.billing_account_id OR r.outcome<>'opened' THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='a migration opening belongs to an opened account result of the same run and account';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM idempotency_registry g WHERE g.id=NEW.idempotency_registry_id
                 AND g.namespace='billing.migration.opening' AND g.key=NEW.opening_key) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='a migration opening requires its own idempotency claim';
  END IF;
  SELECT organization_id INTO v_org FROM billing_accounts WHERE id=NEW.billing_account_id;
  SELECT operator_user_id INTO v_operator FROM billing_migration_runs WHERE id=NEW.run_id;
  IF NOT EXISTS (SELECT 1 FROM billing_migration_establishments e WHERE e.billing_account_id=NEW.billing_account_id
                 AND e.organization_id=v_org AND e.outcome='established') THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='a migration opening requires an established billing account';
  END IF;
  IF NEW.legacy_source_kind='persistent_credit_grant' THEN
    IF NOT {GRANT_SOURCE_SQL.format(o='NEW')} THEN
      RAISE EXCEPTION USING ERRCODE='23514',
        MESSAGE='a persistent-grant opening requires its legacy grant, payment, and payment attribution';
    END IF;
  ELSIF NEW.legacy_source_kind='user_recurring_meter' THEN
    IF NOT EXISTS (SELECT 1 FROM users u JOIN organization_members om ON om.user_id=u.id
        AND om.organization_id=v_org AND om.status='active'
        WHERE u.id=NEW.legacy_source_id AND u.id=NEW.member_attribution_id
          AND phase14_meter_ok(u.ui_preferences::jsonb, NEW.opening_amount, NEW.original_amount,
                               NEW.available_at, NEW.expires_at)) THEN
      RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='a recurring opening requires the member''s live legacy meter';
    END IF;
  ELSIF NEW.legacy_source_kind='organization_recurring_meter' THEN
    IF NEW.legacy_source_id<>v_org OR NOT EXISTS (SELECT 1 FROM organizations o WHERE o.id=v_org
        AND phase14_meter_ok(o.settings::jsonb, NEW.opening_amount, NEW.original_amount,
                             NEW.available_at, NEW.expires_at)) THEN
      RAISE EXCEPTION USING ERRCODE='23514',
        MESSAGE='a recurring opening requires the organization''s live legacy meter';
    END IF;
  ELSE
    SELECT * INTO v FROM billing_migration_reviews WHERE id=NEW.review_id;
    IF v.id IS NULL OR v.id<>NEW.legacy_source_id OR v.billing_account_id<>NEW.billing_account_id
       OR v.subject_user_id IS DISTINCT FROM NEW.member_attribution_id
       OR v.amount<>NEW.opening_amount OR v.amount<>NEW.original_amount
       OR v.expires_at IS DISTINCT FROM NEW.expires_at OR v.expiry_basis<>NEW.expiry_basis THEN
      RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='an unattributed opening must equal its review exactly';
    END IF;
    IF v.reviewer_user_id=v_operator THEN
      RAISE EXCEPTION USING ERRCODE='23514',
        MESSAGE='the operator of a migration run cannot consume a review they approved';
    END IF;
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql""", """
CREATE FUNCTION phase14_opening_final() RETURNS trigger AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM credit_lots l WHERE l.id=NEW.lot_id AND phase14_is_opening_lot(l))
     OR NOT EXISTS (SELECT 1 FROM credit_ledger_entries e WHERE e.id=NEW.ledger_entry_id
                    AND e.entry_type='migration_opening' AND e.lot_id=NEW.lot_id) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='a migration opening must commit with its lot and opening entry';
  END IF;
  RETURN NULL;
END; $$ LANGUAGE plpgsql""", """
CREATE FUNCTION phase14_result_final() RETURNS trigger AS $$
DECLARE opened_count bigint; opened_total bigint;
BEGIN
  SELECT count(*), COALESCE(sum(opening_amount), 0) INTO opened_count, opened_total
  FROM billing_migration_openings WHERE account_result_id=NEW.id;
  IF opened_count<>NEW.opened_count OR opened_total<>NEW.opened_total THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='an account result must equal its openings exactly';
  END IF;
  RETURN NULL;
END; $$ LANGUAGE plpgsql""", f"""
CREATE FUNCTION phase14_review_guard() RETURNS trigger AS $$
DECLARE v_org text;
BEGIN
  IF current_setting('transaction_isolation')<>'read committed' THEN
    RAISE EXCEPTION USING ERRCODE='25001', MESSAGE='migration reviews require READ COMMITTED';
  END IF;
  PERFORM 1 FROM billing_staff_permission_grants WHERE id=NEW.staff_permission_grant_id FOR SHARE;
  IF NOT phase14_review_grant_ok(NEW.staff_permission_grant_id, NEW.reviewer_user_id)
     OR NEW.reviewer_user_id=NEW.subject_user_id OR NEW.reviewed_at<>now() THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='a migration review requires an explicit, unrevoked review grant of someone other than its subject';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM idempotency_registry g WHERE g.id=NEW.idempotency_registry_id
                 AND g.namespace='billing.migration.review' AND g.key=NEW.review_key) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='a migration review requires its own idempotency claim';
  END IF;
  SELECT organization_id INTO v_org FROM billing_accounts WHERE id=NEW.billing_account_id;
  IF {BENEFICIARY_SQL.format(reviewer='NEW.reviewer_user_id', org='v_org', account='NEW.billing_account_id')} THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='a member, owner, or payer of the beneficiary organization cannot approve its value';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM users u WHERE u.id=NEW.subject_user_id AND u.credits_remaining>=NEW.amount) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='a migration review cannot exceed the subject''s legacy counter';
  END IF;
  IF NEW.expiry_basis='non_expiring_legacy_contract' AND NOT {ORPHAN_PURCHASE_SQL.format(
      account='NEW.billing_account_id', payment='NEW.expiry_evidence_payment_id', subject='NEW.subject_user_id')} THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='a non-expiring review requires a real non-expiring purchase of its subject that funds no grant';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql""", """
CREATE FUNCTION phase14_establishment_guard() RETURNS trigger AS $$
BEGIN
  IF NEW.billing_account_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM billing_accounts a
      WHERE a.id=NEW.billing_account_id AND a.organization_id=NEW.organization_id) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='an establishment names its own organization''s billing account';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM idempotency_registry g WHERE g.id=NEW.idempotency_registry_id
                 AND g.namespace='billing.migration.establishment' AND g.key=NEW.run_id||':'||NEW.organization_id) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='an establishment requires its own idempotency claim';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql""", """
CREATE FUNCTION phase14_payer_binding_guard() RETURNS trigger AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM billing_migration_establishments e JOIN billing_accounts a ON a.id=e.billing_account_id
      JOIN users u ON u.id=NEW.payer_user_id
      WHERE e.id=NEW.establishment_id AND e.outcome='established' AND e.billing_account_id=NEW.billing_account_id
        AND a.processor=NEW.processor AND a.processor_customer_id=NEW.processor_customer_id
        AND u.stripe_customer_id=NEW.processor_customer_id
        AND (u.id=(SELECT o.owner_user_id FROM organizations o WHERE o.id=e.organization_id)
             OR EXISTS (SELECT 1 FROM organization_members om WHERE om.organization_id=e.organization_id
                        AND om.user_id=u.id))) THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='a payer binding requires an established account carrying the payer''s own processor customer';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql""", """
CREATE FUNCTION phase14_payment_attribution_guard() RETURNS trigger AS $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM billing_migration_payer_bindings b
      JOIN billing_migration_establishments e ON e.id=b.establishment_id
      JOIN payments p ON p.id=NEW.payment_id
      WHERE b.id=NEW.payer_binding_id AND b.establishment_id=NEW.establishment_id
        AND b.billing_account_id=NEW.billing_account_id AND p.user_id=b.payer_user_id
        AND p.external_reference=NEW.external_reference AND p.source=NEW.source AND lower(p.currency)=NEW.currency
        AND p.amount_paid_cents=NEW.amount_paid_cents AND p.amount_due_cents=NEW.amount_due_cents
        AND p.discount_cents=NEW.discount_cents AND p.is_comped=NEW.is_comped
        AND (p.billing_account_id IS NULL OR p.billing_account_id=NEW.billing_account_id)
        AND (p.organization_id IS NULL OR p.organization_id=e.organization_id)) THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='a payment attribution must copy a real legacy payment of the bound payer exactly';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql""", """
CREATE FUNCTION phase14_payment_archive_guard() RETURNS trigger AS $$
BEGIN
  IF NOT """ + ARCHIVE_COPY_SQL.format(n="NEW", same="IS NOT DISTINCT FROM") + """ THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='a payment archive must copy a real legacy payment exactly';
  END IF;
  IF NOT """ + ARCHIVE_CLAIM_SQL.format(n="NEW") + """ THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='a payment archive requires its own idempotency claim';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql""", """
CREATE FUNCTION phase14_plan_mapping_guard() RETURNS trigger AS $$
BEGIN
  IF NOT """ + MAPPING_ESTABLISHED_SQL.format(n="NEW") + """ THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='a plan mapping requires an established billing account of its organization';
  END IF;
  IF NOT """ + MAPPING_CLAIM_SQL.format(n="NEW") + """ THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='a plan mapping requires its own idempotency claim';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql""", """
CREATE FUNCTION phase14_reject_row_change() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Phase 14 migration evidence is immutable'; END;
$$ LANGUAGE plpgsql""", """
CREATE FUNCTION phase14_reject_truncate() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Phase 14 migration evidence cannot be truncated'; END;
$$ LANGUAGE plpgsql""",
        "CREATE TRIGGER trg_phase14_lot_guard BEFORE INSERT ON credit_lots "
        "FOR EACH ROW EXECUTE FUNCTION phase14_lot_guard()",
        "CREATE TRIGGER trg_phase14_entry_guard BEFORE INSERT ON credit_ledger_entries "
        "FOR EACH ROW EXECUTE FUNCTION phase14_entry_guard()",
        "CREATE TRIGGER trg_phase14_opening_guard BEFORE INSERT ON billing_migration_openings "
        "FOR EACH ROW EXECUTE FUNCTION phase14_opening_guard()",
        "CREATE CONSTRAINT TRIGGER trg_phase14_opening_final AFTER INSERT ON billing_migration_openings "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION phase14_opening_final()",
        "CREATE CONSTRAINT TRIGGER trg_phase14_result_final AFTER INSERT ON billing_migration_account_results "
        "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION phase14_result_final()",
        "CREATE TRIGGER trg_phase14_review_guard BEFORE INSERT ON billing_migration_reviews "
        "FOR EACH ROW EXECUTE FUNCTION phase14_review_guard()",
        "CREATE TRIGGER trg_phase14_establishment_guard BEFORE INSERT ON billing_migration_establishments "
        "FOR EACH ROW EXECUTE FUNCTION phase14_establishment_guard()",
        "CREATE TRIGGER trg_phase14_payer_binding_guard BEFORE INSERT ON billing_migration_payer_bindings "
        "FOR EACH ROW EXECUTE FUNCTION phase14_payer_binding_guard()",
        "CREATE TRIGGER trg_phase14_payment_attribution_guard BEFORE INSERT ON billing_migration_payment_attributions "
        "FOR EACH ROW EXECUTE FUNCTION phase14_payment_attribution_guard()",
        "CREATE TRIGGER trg_phase14_payment_archive_guard BEFORE INSERT ON billing_migration_payment_archives "
        "FOR EACH ROW EXECUTE FUNCTION phase14_payment_archive_guard()",
        "CREATE TRIGGER trg_phase14_plan_mapping_guard BEFORE INSERT ON billing_migration_plan_mappings "
        "FOR EACH ROW EXECUTE FUNCTION phase14_plan_mapping_guard()",
    ]
    for table in TABLES:
        statements.append(f"CREATE TRIGGER trg_phase14_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                          "FOR EACH ROW EXECUTE FUNCTION phase14_reject_row_change()")
        statements.append(f"CREATE TRIGGER trg_phase14_{table}_truncate BEFORE TRUNCATE ON {table} "
                          "FOR EACH STATEMENT EXECUTE FUNCTION phase14_reject_truncate()")
    return statements


def _sqlite_meter_ok(container, o):
    meter = f"json_extract({container},'$.thinking_power"
    return (f"(CAST({meter}.remaining') AS INTEGER)={o}.opening_amount "
            f"AND CAST({meter}.cycle_limit') AS INTEGER)={o}.original_amount "
            f"AND COALESCE(CAST({meter}.overage_tokens') AS INTEGER),0)=0 "
            f"AND julianday({meter}.cycle_reset_at'))=julianday({o}.available_at))")


def _sqlite_guards():
    grant_source = GRANT_SOURCE_SQL.format(o="NEW")
    guards = {
        "trg_phase14_lot_insert": (
            "CREATE TRIGGER trg_phase14_lot_insert BEFORE INSERT ON credit_lots "
            f"WHEN NOT {SQLITE_OPENING_MATCH} BEGIN "
            "SELECT RAISE(ABORT,'a migration lot must equal its opening evidence exactly') "
            "WHERE EXISTS (SELECT 1 FROM billing_migration_openings m WHERE m.lot_id=NEW.id "
            "OR (m.id=NEW.source_id AND m.billing_account_id=NEW.billing_account_id)); "
            "SELECT RAISE(ABORT,'legacy_unattributed credit requires a reviewed Phase 14 migration opening') "
            "WHERE NEW.source_type='legacy_unattributed'; END"
        ),
        "trg_phase14_entry_insert": (
            "CREATE TRIGGER trg_phase14_entry_insert BEFORE INSERT ON credit_ledger_entries BEGIN "
            "SELECT RAISE(ABORT,'a migration_opening entry requires its Phase 14 opening evidence') "
            "WHERE NEW.entry_type='migration_opening' AND NOT EXISTS (SELECT 1 FROM billing_migration_openings m "
            "JOIN billing_migration_account_results r ON r.id=m.account_result_id "
            "WHERE m.ledger_entry_id=NEW.id AND m.lot_id=NEW.lot_id AND m.billing_account_id=NEW.billing_account_id "
            "AND m.idempotency_registry_id=NEW.idempotency_registry_id AND m.opening_amount=NEW.available_delta "
            "AND NEW.held_delta=0 AND julianday(m.effective_at)=julianday(NEW.effective_at) AND r.outcome='opened'); "
            "SELECT RAISE(ABORT,'a migration lot is funded only by its migration_opening entry') "
            "WHERE NEW.entry_type='grant' AND EXISTS (SELECT 1 FROM billing_migration_openings m "
            "WHERE m.lot_id=NEW.lot_id); END"
        ),
        "trg_phase14_opening_insert": (
            "CREATE TRIGGER trg_phase14_opening_insert BEFORE INSERT ON billing_migration_openings BEGIN "
            "SELECT RAISE(ABORT,'a migration opening belongs to an opened account result of the same run and account') "
            "WHERE NOT EXISTS (SELECT 1 FROM billing_migration_account_results r WHERE r.id=NEW.account_result_id "
            "AND r.run_id=NEW.run_id AND r.billing_account_id=NEW.billing_account_id AND r.outcome='opened'); "
            "SELECT RAISE(ABORT,'a migration opening requires its own idempotency claim') "
            "WHERE NOT EXISTS (SELECT 1 FROM idempotency_registry g WHERE g.id=NEW.idempotency_registry_id "
            "AND g.namespace='billing.migration.opening' AND g.key=NEW.opening_key); "
            "SELECT RAISE(ABORT,'a migration opening requires an established billing account') "
            "WHERE NOT EXISTS (SELECT 1 FROM billing_migration_establishments e JOIN billing_accounts a "
            "ON a.id=e.billing_account_id AND a.organization_id=e.organization_id "
            "WHERE e.billing_account_id=NEW.billing_account_id AND e.outcome='established'); "
            "SELECT RAISE(ABORT,'a persistent-grant opening requires its legacy grant, payment, and payment attribution') "
            f"WHERE NEW.legacy_source_kind='persistent_credit_grant' AND NOT {grant_source}; "
            "SELECT RAISE(ABORT,'a recurring opening requires the member''s live legacy meter') "
            "WHERE NEW.legacy_source_kind='user_recurring_meter' AND NOT EXISTS (SELECT 1 FROM users u "
            "JOIN billing_accounts a ON a.id=NEW.billing_account_id "
            "JOIN organization_members om ON om.user_id=u.id AND om.organization_id=a.organization_id "
            "AND om.status='active' WHERE u.id=NEW.legacy_source_id AND u.id=NEW.member_attribution_id "
            f"AND {_sqlite_meter_ok('u.ui_preferences', 'NEW')}); "
            "SELECT RAISE(ABORT,'a recurring opening requires the organization''s live legacy meter') "
            "WHERE NEW.legacy_source_kind='organization_recurring_meter' AND NOT EXISTS (SELECT 1 FROM organizations o "
            "JOIN billing_accounts a ON a.id=NEW.billing_account_id AND a.organization_id=o.id "
            f"WHERE o.id=NEW.legacy_source_id AND {_sqlite_meter_ok('o.settings', 'NEW')}); "
            "SELECT RAISE(ABORT,'an unattributed opening must equal its review exactly') "
            "WHERE NEW.legacy_source_kind='reviewed_unattributed' AND NOT EXISTS (SELECT 1 FROM billing_migration_reviews v "
            "WHERE v.id=NEW.review_id AND v.id=NEW.legacy_source_id AND v.billing_account_id=NEW.billing_account_id "
            "AND v.subject_user_id IS NEW.member_attribution_id AND v.amount=NEW.opening_amount "
            "AND v.amount=NEW.original_amount AND v.expiry_basis=NEW.expiry_basis "
            "AND ((v.expires_at IS NULL AND NEW.expires_at IS NULL) "
            "OR julianday(v.expires_at)=julianday(NEW.expires_at))); "
            "SELECT RAISE(ABORT,'the operator of a migration run cannot consume a review they approved') "
            "WHERE NEW.review_id IS NOT NULL AND EXISTS (SELECT 1 FROM billing_migration_reviews v "
            "JOIN billing_migration_runs rn ON rn.id=NEW.run_id "
            "WHERE v.id=NEW.review_id AND v.reviewer_user_id=rn.operator_user_id); END"
        ),
        "trg_phase14_review_insert": (
            "CREATE TRIGGER trg_phase14_review_insert BEFORE INSERT ON billing_migration_reviews BEGIN "
            "SELECT RAISE(ABORT,'a migration review requires an explicit, unrevoked review grant of someone other "
            "than its subject') WHERE NEW.reviewer_user_id=NEW.subject_user_id OR NOT EXISTS ("
            "SELECT 1 FROM billing_staff_permission_grants g WHERE g.id=NEW.staff_permission_grant_id "
            f"AND g.user_id=NEW.reviewer_user_id AND g.permission={REVIEW_PERMISSION} AND g.permission_version=1 "
            "AND julianday(g.starts_at)<=julianday('now') AND (g.ends_at IS NULL OR julianday(g.ends_at)>julianday('now')) "
            "AND NOT EXISTS (SELECT 1 FROM billing_staff_permission_revocations r WHERE r.grant_id=g.id)); "
            "SELECT RAISE(ABORT,'a member, owner, or payer of the beneficiary organization cannot approve its value') "
            "WHERE " + BENEFICIARY_SQL.format(
                reviewer="NEW.reviewer_user_id",
                org="(SELECT a.organization_id FROM billing_accounts a WHERE a.id=NEW.billing_account_id)",
                account="NEW.billing_account_id") + "; "
            "SELECT RAISE(ABORT,'a migration review cannot exceed the subject''s legacy counter') "
            "WHERE NOT EXISTS (SELECT 1 FROM users u WHERE u.id=NEW.subject_user_id AND u.credits_remaining>=NEW.amount); "
            "SELECT RAISE(ABORT,'a non-expiring review requires a real non-expiring purchase of its subject that funds "
            "no grant') WHERE NEW.expiry_basis='non_expiring_legacy_contract' AND NOT " + ORPHAN_PURCHASE_SQL.format(
                account="NEW.billing_account_id", payment="NEW.expiry_evidence_payment_id",
                subject="NEW.subject_user_id") + "; END"
        ),
        "trg_phase14_establishment_insert": (
            "CREATE TRIGGER trg_phase14_establishment_insert BEFORE INSERT ON billing_migration_establishments BEGIN "
            "SELECT RAISE(ABORT,'an establishment names its own organization''s billing account') "
            "WHERE NEW.billing_account_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM billing_accounts a "
            "WHERE a.id=NEW.billing_account_id AND a.organization_id=NEW.organization_id); "
            "SELECT RAISE(ABORT,'an establishment requires its own idempotency claim') "
            "WHERE NOT EXISTS (SELECT 1 FROM idempotency_registry g WHERE g.id=NEW.idempotency_registry_id "
            "AND g.namespace='billing.migration.establishment' AND g.key=NEW.run_id||':'||NEW.organization_id); END"
        ),
        "trg_phase14_payer_binding_insert": (
            "CREATE TRIGGER trg_phase14_payer_binding_insert BEFORE INSERT ON billing_migration_payer_bindings BEGIN "
            "SELECT RAISE(ABORT,'a payer binding requires an established account carrying the payer''s own processor "
            "customer') WHERE NOT EXISTS (SELECT 1 FROM billing_migration_establishments e "
            "JOIN billing_accounts a ON a.id=e.billing_account_id JOIN users u ON u.id=NEW.payer_user_id "
            "WHERE e.id=NEW.establishment_id AND e.outcome='established' AND e.billing_account_id=NEW.billing_account_id "
            "AND a.processor=NEW.processor AND a.processor_customer_id=NEW.processor_customer_id "
            "AND u.stripe_customer_id=NEW.processor_customer_id "
            "AND (u.id=(SELECT o.owner_user_id FROM organizations o WHERE o.id=e.organization_id) "
            "OR EXISTS (SELECT 1 FROM organization_members om WHERE om.organization_id=e.organization_id "
            "AND om.user_id=u.id))); END"
        ),
        "trg_phase14_payment_attribution_insert": (
            "CREATE TRIGGER trg_phase14_payment_attribution_insert BEFORE INSERT ON "
            "billing_migration_payment_attributions BEGIN "
            "SELECT RAISE(ABORT,'a payment attribution must copy a real legacy payment of the bound payer exactly') "
            "WHERE NOT EXISTS (SELECT 1 FROM billing_migration_payer_bindings b "
            "JOIN billing_migration_establishments e ON e.id=b.establishment_id JOIN payments p ON p.id=NEW.payment_id "
            "WHERE b.id=NEW.payer_binding_id AND b.establishment_id=NEW.establishment_id "
            "AND b.billing_account_id=NEW.billing_account_id AND p.user_id=b.payer_user_id "
            "AND p.external_reference=NEW.external_reference AND p.source=NEW.source AND lower(p.currency)=NEW.currency "
            "AND p.amount_paid_cents=NEW.amount_paid_cents AND p.amount_due_cents=NEW.amount_due_cents "
            "AND p.discount_cents=NEW.discount_cents AND p.is_comped=NEW.is_comped "
            "AND (p.billing_account_id IS NULL OR p.billing_account_id=NEW.billing_account_id) "
            "AND (p.organization_id IS NULL OR p.organization_id=e.organization_id)); END"
        ),
        "trg_phase14_payment_archive_insert": (
            "CREATE TRIGGER trg_phase14_payment_archive_insert BEFORE INSERT ON billing_migration_payment_archives "
            "BEGIN SELECT RAISE(ABORT,'a payment archive must copy a real legacy payment exactly') WHERE NOT "
            + ARCHIVE_COPY_SQL.format(n="NEW", same="IS") + "; "
            "SELECT RAISE(ABORT,'a payment archive requires its own idempotency claim') WHERE NOT "
            + ARCHIVE_CLAIM_SQL.format(n="NEW") + "; END"
        ),
        "trg_phase14_plan_mapping_insert": (
            "CREATE TRIGGER trg_phase14_plan_mapping_insert BEFORE INSERT ON billing_migration_plan_mappings "
            "BEGIN SELECT RAISE(ABORT,'a plan mapping requires an established billing account of its organization') "
            "WHERE NOT " + MAPPING_ESTABLISHED_SQL.format(n="NEW") + "; "
            "SELECT RAISE(ABORT,'a plan mapping requires its own idempotency claim') WHERE NOT "
            + MAPPING_CLAIM_SQL.format(n="NEW") + "; END"
        ),
    }
    for table in TABLES:
        for action in ("update", "delete"):
            guards[f"trg_phase14_{table}_{action}"] = (
                f"CREATE TRIGGER trg_phase14_{table}_{action} BEFORE {action.upper()} ON {table} "
                "BEGIN SELECT RAISE(ABORT,'Phase 14 migration evidence is immutable'); END"
            )
    return guards


SQLITE_TRIGGERS = tuple(_sqlite_guards())


def _replace_permission_check(forward):
    table, name, old, new = PERMISSION_CHECK
    before, after = (old, new) if forward else (new, old)
    if op.get_bind().dialect.name == "postgresql":
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
        op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({after})")
    else:
        _phase11()._sqlite_replace_check(table, before, after)


def upgrade():
    _create_tables()
    _replace_permission_check(forward=True)
    if op.get_bind().dialect.name == "postgresql":
        for statement in _pg_guards():
            op.execute(statement)
        _pg_patch_earlier_guards(forward=True)
    else:
        for statement in _sqlite_guards().values():
            op.execute(statement)
        _sqlite_patch_earlier_guards(forward=True)


def downgrade():
    bind = op.get_bind()
    pg = bind.dialect.name == "postgresql"
    if pg:
        for table in TABLES + ("billing_staff_permission_grants",):
            op.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    for table in TABLES:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None:
            raise Phase14EvidenceNotEmptyError("Phase 14 downgrade refuses to discard migration evidence")
    if bind.execute(sa.text(
            f"SELECT 1 FROM billing_staff_permission_grants WHERE permission={REVIEW_PERMISSION} LIMIT 1")).first():
        raise Phase14EvidenceNotEmptyError("Phase 14 downgrade refuses to discard a migration review permission grant")
    if pg:
        _pg_patch_earlier_guards(forward=False)
        for name, table in PG_TRIGGERS:
            op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
        for name, signature in PG_FUNCTIONS:
            op.execute(f"DROP FUNCTION IF EXISTS {name}({signature})")
    else:
        _sqlite_patch_earlier_guards(forward=False)
        for name in SQLITE_TRIGGERS:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
    _replace_permission_check(forward=False)
    for table in TABLES:
        op.drop_table(table)
