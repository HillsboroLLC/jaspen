"""Add inactive Phase 11 Enterprise contracts and term-bound credit expiry.

Founder-approved directions (2026-11-15):

* P11-DEP-001: annual-term monthly releases (and annual upgrade proration)
  expire at the paid annual term end; monthly and Free are unchanged.
* Credit-pack policy: a purchased pack expires at the end of the paid
  monthly or annual term in force when it was paid (no indefinite validity).
* P11-DEP-003: ``billing.enterprise_contract.manage`` staff permission.
* P11-DEP-004 option A: each paid contract term is a contract-backed
  ``billing_subscriptions`` row; Enterprise entitlements, allocations, and
  seat commitments reuse Phases 4, 6, and 8.

Earlier-phase guard bodies are not retyped: they are captured from their own
revisions and patched with exact, asserted substitutions, so everything except
the approved change stays byte-identical. Downgrade restores those captured
originals and refuses to discard Phase 11 evidence or re-tighten rules that
existing rows already rely on.

Revision ID: b4d6f8a0c2e5
Revises: f2b4d6e8a0c3
"""

from importlib import import_module
import re

from alembic import op
import sqlalchemy as sa


revision = "b4d6f8a0c2e5"
down_revision = "f2b4d6e8a0c3"
branch_labels = None
depends_on = None


TABLES = (
    "enterprise_contract_notices", "enterprise_contract_activations",
    "enterprise_contract_term_fundings", "enterprise_contract_events",
    "enterprise_contract_versions", "enterprise_contracts",
)
CONTRACT = "'jaspen_contract'"
PERMISSION = "'billing.enterprise_contract.manage'"

CHECKS = (
    (
        "entitlement_instances", "ck_entitlement_instances_source_reference",
        "((source_type = 'subscription' AND subscription_id IS NOT NULL) OR "
        "(source_type != 'subscription' AND subscription_id IS NULL))",
        "((source_type IN ('subscription','enterprise_contract') AND subscription_id IS NOT NULL) OR "
        "(source_type NOT IN ('subscription','enterprise_contract') AND subscription_id IS NULL))",
    ),
    (
        "entitlement_instances", "ck_entitlement_instances_later_authority_gate",
        "source_type <> 'enterprise_contract' OR state IN ('proposed','cancelled')",
        "source_type <> 'enterprise_contract' OR subscription_id IS NOT NULL",
    ),
    (
        "billing_staff_permission_grants", "ck_billing_staff_permission_grants_permission",
        "permission IN ('billing.comp.grant', 'billing.internal_funding.grant')",
        "permission IN ('billing.comp.grant', 'billing.internal_funding.grant', "
        "'billing.enterprise_contract.manage')",
    ),
    (
        "seat_commitments", "ck_seat_commitments_lineage",
        "(origin_type='opening' AND previous_commitment_id IS NULL) OR (origin_type<>'opening' AND previous_commitment_id IS NOT NULL)",
        "(origin_type IN ('opening','contract') AND previous_commitment_id IS NULL) OR (origin_type<>'opening' AND previous_commitment_id IS NOT NULL)",
    ),
    (
        "seat_commitments", "ck_seat_commitments_origin",
        "origin_type IN ('opening','increase','reduction')",
        "origin_type IN ('opening','increase','reduction','contract')",
    ),
)

# Customer plan and seat commands never act on a contract-backed term.
CONTRACT_REFUSED_TABLES = (
    "scheduled_plan_changes", "upgrade_credit_allocations", "seat_changes",
    "seat_funding_attributions", "seat_term_fundings",
)


class Phase11EvidenceNotEmptyError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Capturing earlier revisions' guard text
# ---------------------------------------------------------------------------

class _Recorder:
    def __init__(self):
        self.statements = []

    def execute(self, statement, *_args, **_kwargs):
        self.statements.append(str(statement))


def _captured(module_name, function_name):
    module = import_module(f"migrations.versions.{module_name}")
    recorder, original = _Recorder(), module.op
    module.op = recorder
    try:
        getattr(module, function_name)()
    finally:
        module.op = original
    return "\n".join(recorder.statements)


def _pg_function(text, name):
    match = re.search(
        r"CREATE (?:OR REPLACE )?FUNCTION " + re.escape(name) + r"\(\).*?\$\$ LANGUAGE plpgsql;?",
        text, re.S,
    )
    if match is None:
        raise RuntimeError(f"guard function {name} was not found in its revision")
    body = match.group(0).rstrip(";")
    return re.sub(r"^CREATE (?:OR REPLACE )?FUNCTION", "CREATE OR REPLACE FUNCTION", body)


def _sqlite_trigger(text, name):
    match = re.search(r"CREATE TRIGGER " + re.escape(name) + r"\b.*?\bEND\b(?=\s*(?:$|CREATE))", text, re.S)
    if match is None:
        raise RuntimeError(f"trigger {name} was not found in its revision")
    return match.group(0)


def _patched(text, replacements):
    for old, new in replacements:
        if text.count(old) != 1:
            raise RuntimeError(f"guard text is not in the expected form: {old[:60]!r}")
        text = text.replace(old, new)
    return text


_CONTRACT_ALLOCATION_EVIDENCE_PG = (
    "EXISTS (SELECT 1 FROM enterprise_contract_term_fundings f "
    "JOIN enterprise_contract_versions v ON v.id=f.version_id "
    "JOIN enterprise_contract_activations act ON act.version_id=v.id AND act.term_funding_id=f.id "
    "WHERE f.financial_line_id=NEW.financial_line_id AND f.subscription_id=NEW.subscription_id "
    "AND v.version_kind IN ('initial','renewal') AND v.entitlement_instance_id=NEW.entitlement_instance_id)"
)
_TERM_END_FOR_PERIOD = (
    "(CASE WHEN p.kind='annual_monthly' THEN (SELECT s.term_ends_at FROM billing_subscriptions s "
    "WHERE s.id=p.subscription_id) ELSE p.ends_at END)"
)
_TERM_END_FOR_UPGRADE = (
    "(CASE WHEN (SELECT s.interval FROM billing_subscriptions s WHERE s.id=a.subscription_id)='year' "
    "THEN (SELECT s.term_ends_at FROM billing_subscriptions s WHERE s.id=a.subscription_id) "
    "ELSE a.period_ends_at END)"
)
_PAID_TERM_PG = (
    "s.billing_account_id=NEW.billing_account_id AND s.state IN ('active','past_due','cancel_at_period_end') "
    "AND s.interval IN ('month','year') AND s.term_starts_at<=NEW.paid_at AND s.term_ends_at>NEW.paid_at"
)


def _pg_originals():
    phase4 = _captured("f9c1a3e5b7d4_add_entitlement_and_credit_period_foundations", "_postgresql_triggers")
    phase6 = _captured("f5c8d3e0b2a1_add_recurring_credit_allocations", "_postgresql_triggers")
    phase7 = _captured("a7d9e2f4b6c8_add_plan_changes_and_upgrade_proration", "_postgresql_guards")
    phase9 = _captured("e1a3c5b7d9f2_add_financial_effects", "_postgresql_guards")
    return {
        "phase4_period_guard": _pg_function(phase4, "phase4_period_guard"),
        "phase7_upgrade_final": _pg_function(phase7, "phase7_upgrade_final"),
        "phase6_allocation_guard": _pg_function(phase6, "phase6_allocation_guard"),
        "phase6_period_guard": _pg_function(phase6, "phase6_period_guard"),
        "phase6_recurring_lot_guard": _pg_function(phase7, "phase6_recurring_lot_guard"),
        "phase9_purchase_funding_guard": _pg_function(phase9, "phase9_purchase_funding_guard"),
        "phase9_purchase_lot_guard": _pg_function(phase9, "phase9_purchase_lot_guard"),
    }


def _pg_replacements(originals):
    return {
        "phase4_period_guard": _patched(originals["phase4_period_guard"], (
            ("lot_row.expires_at<>NEW.ends_at",
             "lot_row.expires_at<>(CASE WHEN NEW.kind='annual_monthly' THEN (SELECT s.term_ends_at FROM "
             "billing_subscriptions s WHERE s.id=NEW.subscription_id) ELSE NEW.ends_at END)"),
        )),
        "phase7_upgrade_final": _patched(originals["phase7_upgrade_final"], (
            ("lot.expires_at<>a.period_ends_at", f"lot.expires_at<>{_TERM_END_FOR_UPGRADE}"),
        )),
        "phase6_allocation_guard": _patched(originals["phase6_allocation_guard"], (
            ("OR instance_row.source_type <> 'subscription'",
             f"OR instance_row.source_type <> (CASE WHEN subscription_row.processor={CONTRACT} "
             "THEN 'enterprise_contract' ELSE 'subscription' END)"),
            ("OR (NEW.period_kind='monthly_subscription' AND NOT (",
             f"OR (subscription_row.processor <> {CONTRACT} AND NEW.period_kind='monthly_subscription' AND NOT ("),
            ("OR (NEW.period_kind='annual_monthly' AND NOT (",
             f"OR (subscription_row.processor <> {CONTRACT} AND NEW.period_kind='annual_monthly' AND NOT ("),
            ("AND financial_row.effective_at < subscription_row.term_ends_at)) THEN",
             "AND financial_row.effective_at < subscription_row.term_ends_at))\n"
             f"          OR (subscription_row.processor = {CONTRACT} AND NOT {_CONTRACT_ALLOCATION_EVIDENCE_PG}) THEN"),
        )),
        "phase6_period_guard": _patched(originals["phase6_period_guard"], (
            ("IF CURRENT_TIMESTAMP < OLD.ends_at THEN",
             "IF CURRENT_TIMESTAMP < COALESCE((SELECT expires_at FROM credit_lots WHERE id=OLD.funded_lot_id), "
             "OLD.ends_at) THEN"),
        )),
        "phase6_recurring_lot_guard": _patched(originals["phase6_recurring_lot_guard"], (
            ("a.period_ends_at=NEW.expires_at", f"NEW.expires_at={_TERM_END_FOR_UPGRADE}"),
            ("p.ends_at=NEW.expires_at", f"NEW.expires_at={_TERM_END_FOR_PERIOD}"),
        )),
        "phase9_purchase_funding_guard": _patched(originals["phase9_purchase_funding_guard"], (
            ("""OR terms->'expiry' IS DISTINCT FROM '{"kind":"none"}'::jsonb""",
             """OR terms->'expiry' IS DISTINCT FROM '{"kind":"current_term_end"}'::jsonb"""),
            ("      RETURN NEW;\n    END;",
             "      IF NEW.expiry_subscription_id IS NULL OR NEW.expires_at IS NULL OR NOT EXISTS (\n"
             "           SELECT 1 FROM billing_subscriptions s WHERE s.id=NEW.expiry_subscription_id\n"
             f"             AND {_PAID_TERM_PG} AND s.term_ends_at=NEW.expires_at)\n"
             f"         OR (SELECT count(*) FROM billing_subscriptions s WHERE {_PAID_TERM_PG}) <> 1 THEN\n"
             "        RAISE EXCEPTION USING ERRCODE='23514',\n"
             "          MESSAGE='purchased credit must expire at the end of the one paid term in force at payment';\n"
             "      END IF;\n"
             "      RETURN NEW;\n    END;"),
        )),
        "phase9_purchase_lot_guard": _patched(originals["phase9_purchase_lot_guard"], (
            ("AND f.paid_at=NEW.available_at AND NEW.expires_at IS NULL)",
             "AND f.paid_at=NEW.available_at AND f.expires_at IS NOT NULL AND NEW.expires_at=f.expires_at)"),
        )),
    }


def _sqlite_originals():
    phase4 = _captured("f9c1a3e5b7d4_add_entitlement_and_credit_period_foundations", "_sqlite_triggers")
    phase6 = _captured("f5c8d3e0b2a1_add_recurring_credit_allocations", "_sqlite_triggers")
    phase9 = _captured("e1a3c5b7d9f2_add_financial_effects", "_sqlite_guards")
    return {
        "trg_phase4_period_update": _sqlite_trigger(phase4, "trg_phase4_period_update"),
        "trg_phase6_allocation_insert": _sqlite_trigger(phase6, "trg_phase6_allocation_insert"),
        "trg_phase6_recurring_lot_insert": _sqlite_trigger(phase6, "trg_phase6_recurring_lot_insert"),
        "trg_phase6_period_update": _sqlite_trigger(phase6, "trg_phase6_period_update"),
        "trg_phase9_purchase_lot_insert": _sqlite_trigger(phase9, "trg_phase9_purchase_lot_insert"),
    }


_CONTRACT_ALLOCATION_EVIDENCE_SQLITE = (
    "EXISTS (SELECT 1 FROM enterprise_contract_term_fundings f "
    "JOIN enterprise_contract_versions v ON v.id=f.version_id "
    "JOIN enterprise_contract_activations act ON act.version_id=v.id AND act.term_funding_id=f.id "
    "WHERE f.financial_line_id=NEW.financial_line_id AND f.subscription_id=NEW.subscription_id "
    "AND v.version_kind IN ('initial','renewal') AND v.entitlement_instance_id=NEW.entitlement_instance_id)"
)


def _sqlite_replacements(originals):
    return {
        "trg_phase4_period_update": _patched(originals["trg_phase4_period_update"], (
            ("AND julianday(lot.expires_at)=julianday(NEW.ends_at)",
             "AND julianday(lot.expires_at)=julianday(CASE WHEN NEW.kind='annual_monthly' THEN "
             "(SELECT s.term_ends_at FROM billing_subscriptions s WHERE s.id=NEW.subscription_id) "
             "ELSE NEW.ends_at END)"),
        )),
        "trg_phase6_allocation_insert": _patched(originals["trg_phase6_allocation_insert"], (
            ("WHERE period.id=NEW.credit_period_id AND instance.source_type='subscription'",
             "WHERE period.id=NEW.credit_period_id AND instance.source_type=CASE WHEN "
             f"subscription.processor={CONTRACT} THEN 'enterprise_contract' ELSE 'subscription' END"),
            ("AND ((NEW.period_kind='monthly_subscription'\n              AND julianday(financial.effective_at)",
             f"AND ((subscription.processor={CONTRACT}) OR (NEW.period_kind='monthly_subscription'\n"
             "              AND julianday(financial.effective_at)"),
            ("    END", "      SELECT RAISE(ABORT,'contract allocation requires the activated term''s verified funding')\n"
             f"      WHERE (SELECT processor FROM billing_subscriptions WHERE id=NEW.subscription_id)={CONTRACT}\n"
             f"        AND NOT {_CONTRACT_ALLOCATION_EVIDENCE_SQLITE};\n    END"),
        )),
        "trg_phase6_recurring_lot_insert": _patched(originals["trg_phase6_recurring_lot_insert"], (
            ("AND julianday(period.ends_at)=julianday(NEW.expires_at)",
             "AND julianday(NEW.expires_at)=julianday(CASE WHEN period.kind='annual_monthly' THEN "
             "(SELECT s.term_ends_at FROM billing_subscriptions s WHERE s.id=period.subscription_id) "
             "ELSE period.ends_at END)"),
        )),
        "trg_phase6_period_update": _patched(originals["trg_phase6_period_update"], (
            ("AND julianday(CURRENT_TIMESTAMP)<julianday(OLD.ends_at);",
             "AND julianday(CURRENT_TIMESTAMP)<julianday(COALESCE("
             "(SELECT expires_at FROM credit_lots WHERE id=OLD.funded_lot_id), OLD.ends_at));"),
        )),
        "trg_phase9_purchase_lot_insert": _patched(originals["trg_phase9_purchase_lot_insert"], (
            ("AND NEW.expires_at IS NULL)",
             "AND f.expires_at IS NOT NULL AND julianday(NEW.expires_at)=julianday(f.expires_at))"),
        )),
    }


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

def _id():
    return sa.Column("id", sa.String(36), primary_key=True)


def _ref(name, table, nullable=False):
    return sa.Column(name, sa.String(36), sa.ForeignKey(f"{table}.id", ondelete="RESTRICT"), nullable=nullable)


def _ts(name, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _create_tables():
    op.create_table(
        "enterprise_contracts",
        _id(),
        _ref("billing_account_id", "billing_accounts"),
        sa.Column("contract_reference", sa.String(255), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="recorded"),
        sa.Column("last_event_id", sa.String(36), nullable=True),
        _ts("paid_access_ended_at", True), _ts("retention_review_until", True),
        _ref("idempotency_registry_id", "idempotency_registry"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("contract_reference", name="uq_enterprise_contracts_reference"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_enterprise_contracts_registry"),
        sa.CheckConstraint(
            "state IN ('recorded','approved','active','renewal_grace','ended','cancelled')",
            name="ck_enterprise_contracts_state",
        ),
        sa.CheckConstraint("length(trim(contract_reference)) > 0", name="ck_enterprise_contracts_reference"),
        sa.CheckConstraint(
            "(paid_access_ended_at IS NULL) = (retention_review_until IS NULL) "
            "AND (paid_access_ended_at IS NULL OR retention_review_until > paid_access_ended_at)",
            name="ck_enterprise_contracts_retention",
        ),
        sa.CheckConstraint(
            "(state = 'ended') = (paid_access_ended_at IS NOT NULL) OR state = 'cancelled'",
            name="ck_enterprise_contracts_ended_shape",
        ),
    )
    op.create_index("ix_enterprise_contracts_account_state", "enterprise_contracts", ["billing_account_id", "state"])
    op.create_table(
        "enterprise_contract_versions",
        _id(),
        _ref("contract_id", "enterprise_contracts"),
        _ref("billing_account_id", "billing_accounts"),
        sa.Column("version_number", sa.Integer, nullable=False),
        sa.Column("version_kind", sa.String(16), nullable=False),
        _ref("term_version_id", "enterprise_contract_versions", True),
        sa.Column("interval", sa.String(8), nullable=True),
        _ts("term_starts_at", True), _ts("term_ends_at", True), _ts("effective_at"),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("price_minor", sa.BigInteger, nullable=False),
        sa.Column("monthly_credit_amount", sa.BigInteger, nullable=True),
        sa.Column("committed_seats", sa.Integer, nullable=False),
        sa.Column("capabilities_json", sa.JSON, nullable=True),
        sa.Column("exclusivity_key", sa.String(80), nullable=True),
        sa.Column("renewal_mode", sa.String(16), nullable=True),
        sa.Column("executed_reference", sa.String(255), nullable=False),
        sa.Column("executed_evidence_reference", sa.String(255), nullable=False),
        _ref("recorded_by_user_id", "users"),
        _ref("recorded_permission_grant_id", "billing_staff_permission_grants"),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        _ref("idempotency_registry_id", "idempotency_registry"),
        _ts("recorded_at"),
        sa.Column("state", sa.String(16), nullable=False, server_default="recorded"),
        sa.Column("last_event_id", sa.String(36), nullable=True),
        _ref("entitlement_definition_id", "entitlement_definitions", True),
        _ref("subscription_id", "billing_subscriptions", True),
        _ref("entitlement_instance_id", "entitlement_instances", True),
        sa.UniqueConstraint("contract_id", "version_number", name="uq_enterprise_contract_versions_number"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_enterprise_contract_versions_registry"),
        sa.CheckConstraint("version_number > 0", name="ck_enterprise_contract_versions_number"),
        sa.CheckConstraint(
            "version_kind IN ('initial','renewal','amendment')", name="ck_enterprise_contract_versions_kind",
        ),
        sa.CheckConstraint(
            "state IN ('recorded','approved','active','completed','cancelled','superseded')",
            name="ck_enterprise_contract_versions_state",
        ),
        sa.CheckConstraint("price_minor > 0 AND committed_seats > 0", name="ck_enterprise_contract_versions_amounts"),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = lower(currency)", name="ck_enterprise_contract_versions_currency",
        ),
        sa.CheckConstraint(
            "length(trim(executed_reference)) > 0 AND length(trim(executed_evidence_reference)) > 0 "
            "AND length(request_fingerprint) = 64",
            name="ck_enterprise_contract_versions_evidence",
        ),
        sa.CheckConstraint(
            "(version_kind IN ('initial','renewal') AND interval IN ('month','year') "
            " AND term_starts_at IS NOT NULL AND term_ends_at > term_starts_at "
            " AND effective_at = term_starts_at AND monthly_credit_amount > 0 "
            " AND capabilities_json IS NOT NULL AND renewal_mode IN ('manual','automatic') "
            " AND length(trim(exclusivity_key)) > 0 "
            " AND ((version_kind = 'initial' AND term_version_id IS NULL) "
            "   OR (version_kind = 'renewal' AND term_version_id IS NOT NULL))) "
            "OR (version_kind = 'amendment' AND term_version_id IS NOT NULL AND interval IS NULL "
            " AND term_starts_at IS NULL AND term_ends_at IS NULL AND monthly_credit_amount IS NULL "
            " AND capabilities_json IS NULL AND renewal_mode IS NULL AND exclusivity_key IS NULL)",
            name="ck_enterprise_contract_versions_shape",
        ),
    )
    op.create_index(
        "ix_enterprise_contract_versions_contract_state", "enterprise_contract_versions", ["contract_id", "state"],
    )
    op.create_index("ix_enterprise_contract_versions_term", "enterprise_contract_versions", ["term_version_id"])
    op.create_table(
        "enterprise_contract_events",
        _id(),
        _ref("contract_id", "enterprise_contracts"),
        _ref("version_id", "enterprise_contract_versions", True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("transition", sa.String(64), nullable=False),
        sa.Column("from_state", sa.String(16), nullable=False),
        sa.Column("to_state", sa.String(16), nullable=False),
        _ts("occurred_at"),
        _ref("actor_user_id", "users"),
        _ref("permission_grant_id", "billing_staff_permission_grants"),
        sa.Column("reason", sa.String(2000), nullable=True),
        sa.Column("evidence_reference", sa.String(255), nullable=False),
        _ref("idempotency_registry_id", "idempotency_registry"),
        _ref("domain_event_id", "domain_events"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_enterprise_contract_events_registry"),
        sa.CheckConstraint("scope IN ('contract','version')", name="ck_enterprise_contract_events_scope"),
        sa.CheckConstraint(
            "(scope = 'contract') = (version_id IS NULL) AND from_state <> to_state "
            "AND length(trim(transition)) > 0 AND length(trim(evidence_reference)) > 0",
            name="ck_enterprise_contract_events_shape",
        ),
    )
    op.create_index(
        "ix_enterprise_contract_events_contract", "enterprise_contract_events", ["contract_id", "occurred_at", "id"],
    )
    op.create_table(
        "enterprise_contract_term_fundings",
        _id(),
        _ref("contract_id", "enterprise_contracts"),
        _ref("version_id", "enterprise_contract_versions"),
        _ref("billing_account_id", "billing_accounts"),
        _ref("subscription_id", "billing_subscriptions"),
        _ref("financial_transaction_id", "financial_transactions"),
        _ref("financial_line_id", "financial_lines"),
        sa.Column("amount_minor", sa.BigInteger, nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        _ts("paid_at"), _ts("recorded_at"),
        _ref("actor_user_id", "users"),
        _ref("permission_grant_id", "billing_staff_permission_grants"),
        _ref("idempotency_registry_id", "idempotency_registry"),
        _ref("domain_event_id", "domain_events"),
        sa.UniqueConstraint("version_id", name="uq_enterprise_contract_term_fundings_version"),
        sa.UniqueConstraint("financial_line_id", name="uq_enterprise_contract_term_fundings_line"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_enterprise_contract_term_fundings_registry"),
        sa.CheckConstraint("amount_minor > 0", name="ck_enterprise_contract_term_fundings_amount"),
    )
    op.create_index(
        "ix_enterprise_contract_term_fundings_subscription", "enterprise_contract_term_fundings", ["subscription_id"],
    )
    op.create_table(
        "enterprise_contract_activations",
        _id(),
        _ref("contract_id", "enterprise_contracts"),
        _ref("version_id", "enterprise_contract_versions"),
        _ref("billing_account_id", "billing_accounts"),
        _ref("subscription_id", "billing_subscriptions"),
        _ref("entitlement_instance_id", "entitlement_instances", True),
        _ref("term_funding_id", "enterprise_contract_term_fundings"),
        sa.Column(
            "seat_commitment_id", sa.String(36),
            sa.ForeignKey("seat_commitments.id", ondelete="RESTRICT", deferrable=True, initially="DEFERRED"),
            nullable=False,
        ),
        sa.Column("seats", sa.Integer, nullable=False),
        _ts("activated_at"),
        _ref("actor_user_id", "users"),
        _ref("permission_grant_id", "billing_staff_permission_grants"),
        _ref("idempotency_registry_id", "idempotency_registry"),
        _ref("domain_event_id", "domain_events"),
        sa.UniqueConstraint("version_id", name="uq_enterprise_contract_activations_version"),
        sa.UniqueConstraint("term_funding_id", name="uq_enterprise_contract_activations_funding"),
        sa.UniqueConstraint("seat_commitment_id", name="uq_enterprise_contract_activations_commitment"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_enterprise_contract_activations_registry"),
        sa.CheckConstraint("seats > 0", name="ck_enterprise_contract_activations_seats"),
    )
    op.create_index(
        "ix_enterprise_contract_activations_subscription", "enterprise_contract_activations", ["subscription_id"],
    )
    op.create_table(
        "enterprise_contract_notices",
        _id(),
        _ref("contract_id", "enterprise_contracts"),
        _ref("term_version_id", "enterprise_contract_versions"),
        sa.Column("kind", sa.String(24), nullable=False),
        _ref("reverses_notice_id", "enterprise_contract_notices", True),
        _ts("received_at"), _ts("deadline_at"),
        sa.Column("timely", sa.Boolean, nullable=False),
        sa.Column("evidence_reference", sa.String(255), nullable=False),
        _ref("actor_user_id", "users"),
        _ref("permission_grant_id", "billing_staff_permission_grants"),
        _ref("idempotency_registry_id", "idempotency_registry"),
        _ref("domain_event_id", "domain_events"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_enterprise_contract_notices_registry"),
        sa.UniqueConstraint("reverses_notice_id", name="uq_enterprise_contract_notices_reversal"),
        sa.CheckConstraint(
            "kind IN ('nonrenewal','nonrenewal_reversal')", name="ck_enterprise_contract_notices_kind",
        ),
        sa.CheckConstraint(
            "(kind = 'nonrenewal_reversal') = (reverses_notice_id IS NOT NULL) "
            "AND length(trim(evidence_reference)) > 0",
            name="ck_enterprise_contract_notices_shape",
        ),
    )
    op.create_index(
        "ix_enterprise_contract_notices_term", "enterprise_contract_notices", ["term_version_id", "kind"],
    )
    # Plain ADD COLUMN on both dialects: a SQLite batch rebuild would drop the
    # Phase 9 immutability triggers on this table.
    if op.get_bind().dialect.name == "postgresql":
        op.add_column("credit_purchase_fundings", sa.Column(
            "expiry_subscription_id", sa.String(36),
            sa.ForeignKey(
                "billing_subscriptions.id", name="fk_credit_purchase_fundings_expiry_subscription",
                ondelete="RESTRICT",
            ),
            nullable=True,
        ))
    else:
        op.execute(
            "ALTER TABLE credit_purchase_fundings ADD COLUMN expiry_subscription_id VARCHAR(36) "
            "CONSTRAINT fk_credit_purchase_fundings_expiry_subscription "
            "REFERENCES billing_subscriptions (id) ON DELETE RESTRICT"
        )
    op.add_column("credit_purchase_fundings", sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "ix_credit_purchase_fundings_expiry_subscription", "credit_purchase_fundings", ["expiry_subscription_id"],
    )


def _sqlite_replace_check(table, old_expression, new_expression):
    """Rewrite one CHECK expression in place (the Phase 10 procedure, generalized)."""
    bind = op.get_bind()
    table_sql = bind.execute(
        sa.text("SELECT sql FROM sqlite_master WHERE type='table' AND name=:name"), {"name": table},
    ).scalar_one()
    if table_sql.count(old_expression) == 0 and table_sql.count(new_expression) == 1:
        return
    if table_sql.count(old_expression) != 1:
        raise RuntimeError(f"{table} check constraint is not in the expected form")
    version = bind.execute(sa.text("PRAGMA schema_version")).scalar_one()
    bind.execute(sa.text("PRAGMA writable_schema=ON"))
    try:
        bind.execute(
            sa.text("UPDATE sqlite_master SET sql=:sql WHERE type='table' AND name=:name"),
            {"sql": table_sql.replace(old_expression, new_expression), "name": table},
        )
        bind.execute(sa.text(f"PRAGMA schema_version={int(version) + 1}"))
    finally:
        bind.execute(sa.text("PRAGMA writable_schema=OFF"))
    if bind.execute(sa.text("PRAGMA quick_check")).scalar_one() != "ok":
        raise RuntimeError(f"{table} schema check failed after the constraint change")


def _replace_checks(forward=True):
    bind = op.get_bind()
    for table, name, old, new in CHECKS:
        before, after = (old, new) if forward else (new, old)
        if bind.dialect.name == "postgresql":
            op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {name}")
            op.execute(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({after})")
        else:
            _sqlite_replace_check(table, before, after)


# ---------------------------------------------------------------------------
# PostgreSQL guards
# ---------------------------------------------------------------------------

_PG_PHASE11 = f"""
CREATE FUNCTION phase11_require_read_committed() RETURNS void AS $$
BEGIN
  IF current_setting('transaction_isolation') <> 'read committed' THEN
    RAISE EXCEPTION USING ERRCODE='25001', MESSAGE='Enterprise contract commands require READ COMMITTED';
  END IF;
END; $$ LANGUAGE plpgsql;

-- Explicit, unrevoked Enterprise contract permission, valid at the actual
-- current time (Phase 10 audit R2). Admin identity and billing roles never count.
CREATE FUNCTION phase11_grant_ok(p_grant text, p_user text) RETURNS boolean AS $$
  SELECT p_grant IS NOT NULL AND p_user IS NOT NULL AND EXISTS (
    SELECT 1 FROM billing_staff_permission_grants g
    WHERE g.id=p_grant AND g.user_id=p_user AND g.permission={PERMISSION} AND g.permission_version=1
      AND g.starts_at<=now() AND (g.ends_at IS NULL OR g.ends_at>clock_timestamp())
      AND NOT EXISTS (SELECT 1 FROM billing_staff_permission_revocations r WHERE r.grant_id=g.id));
$$ LANGUAGE sql STABLE;

CREATE FUNCTION phase11_event_ok(p_event text, p_account text, p_type text, p_aggregate text) RETURNS boolean AS $$
  SELECT EXISTS (SELECT 1 FROM domain_events e JOIN communication_outbox o ON o.domain_event_id=e.id
    WHERE e.id=p_event AND e.billing_account_id=p_account AND e.event_type=p_type AND e.aggregate_id=p_aggregate
      AND o.billing_account_id=p_account);
$$ LANGUAGE sql STABLE;

CREATE FUNCTION phase11_claimed(p_registry text, p_namespace text) RETURNS boolean AS $$
  SELECT EXISTS (SELECT 1 FROM idempotency_registry r WHERE r.id=p_registry AND r.namespace=p_namespace
    AND r.state='claimed');
$$ LANGUAGE sql STABLE;

CREATE FUNCTION phase11_reject_row_change() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Phase 11 contract evidence is immutable'; END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION phase11_reject_truncate() RETURNS trigger AS $$
BEGIN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Phase 11 contract evidence cannot be truncated'; END;
$$ LANGUAGE plpgsql;

CREATE FUNCTION phase11_contract_guard() RETURNS trigger AS $$
DECLARE e enterprise_contract_events%ROWTYPE;
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='contracts are historical records'; END IF;
  IF TG_OP='INSERT' THEN
    PERFORM phase11_require_read_committed();
    IF NEW.state<>'recorded' OR NEW.last_event_id IS NOT NULL OR NEW.paid_access_ended_at IS NOT NULL
      OR NOT phase11_claimed(NEW.idempotency_registry_id, 'enterprise_contract_command') THEN
      RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='a contract begins recorded under its own claim';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.billing_account_id IS DISTINCT FROM OLD.billing_account_id
    OR NEW.contract_reference IS DISTINCT FROM OLD.contract_reference
    OR NEW.idempotency_registry_id IS DISTINCT FROM OLD.idempotency_registry_id
    OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='contract identity is immutable';
  END IF;
  IF NEW.state IS DISTINCT FROM OLD.state OR NEW.last_event_id IS DISTINCT FROM OLD.last_event_id THEN
    SELECT * INTO e FROM enterprise_contract_events WHERE id=NEW.last_event_id;
    IF e.id IS NULL OR NEW.last_event_id IS NOT DISTINCT FROM OLD.last_event_id OR e.contract_id<>NEW.id
      OR e.scope<>'contract' OR e.from_state<>OLD.state OR e.to_state<>NEW.state THEN
      RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='contract state changes require an append-only event';
    END IF;
  END IF;
  IF (NEW.paid_access_ended_at IS DISTINCT FROM OLD.paid_access_ended_at
      OR NEW.retention_review_until IS DISTINCT FROM OLD.retention_review_until)
    AND NOT (OLD.paid_access_ended_at IS NULL AND NEW.state='ended' AND OLD.state<>'ended')
    -- B1: a renewal paid within grace but processed after it lapsed reinstates the contract.
    AND NOT (OLD.state='ended' AND NEW.state='active' AND NEW.paid_access_ended_at IS NULL
      AND NEW.retention_review_until IS NULL AND e.transition='reinstated_after_grace_payment'
      AND EXISTS (SELECT 1 FROM enterprise_contract_events ended WHERE ended.id=OLD.last_event_id
            AND ended.transition='ended_after_unpaid_grace')
      AND EXISTS (SELECT 1 FROM enterprise_contract_activations a
            JOIN enterprise_contract_versions v ON v.id=a.version_id
            JOIN enterprise_contract_term_fundings f ON f.id=a.term_funding_id
            WHERE v.contract_id=NEW.id AND v.version_kind='renewal' AND v.term_starts_at=OLD.paid_access_ended_at
              AND f.paid_at<OLD.paid_access_ended_at + interval '15 days')) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='end of paid access is recorded once, when the contract ends';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE FUNCTION phase11_version_guard() RETURNS trigger AS $$
DECLARE c enterprise_contracts%ROWTYPE; e enterprise_contract_events%ROWTYPE;
BEGIN
  IF TG_OP='DELETE' THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='contract versions are historical records'; END IF;
  IF TG_OP='INSERT' THEN
    PERFORM phase11_require_read_committed();
    SELECT * INTO c FROM enterprise_contracts WHERE id=NEW.contract_id;
    IF c.id IS NULL OR c.billing_account_id<>NEW.billing_account_id OR c.state IN ('ended','cancelled')
      OR NEW.state<>'recorded' OR NEW.last_event_id IS NOT NULL OR NEW.entitlement_definition_id IS NOT NULL
      OR NEW.subscription_id IS NOT NULL OR NEW.entitlement_instance_id IS NOT NULL
      OR NOT phase11_grant_ok(NEW.recorded_permission_grant_id, NEW.recorded_by_user_id)
      OR NOT phase11_claimed(NEW.idempotency_registry_id, 'enterprise_contract_command')
      OR (NEW.term_version_id IS NOT NULL AND NOT EXISTS (SELECT 1 FROM enterprise_contract_versions t
            WHERE t.id=NEW.term_version_id AND t.contract_id=NEW.contract_id AND t.version_kind IN ('initial','renewal')))
      OR (NEW.version_kind='renewal' AND NOT EXISTS (SELECT 1 FROM enterprise_contract_versions t
            WHERE t.id=NEW.term_version_id AND t.term_ends_at=NEW.term_starts_at))
      OR (NEW.version_kind='amendment' AND NOT EXISTS (SELECT 1 FROM enterprise_contract_versions t
            WHERE t.id=NEW.term_version_id AND NEW.effective_at>=t.term_starts_at AND NEW.effective_at<t.term_ends_at
              AND NEW.committed_seats>t.committed_seats AND NEW.currency=t.currency))
      OR (NEW.version_kind='initial' AND EXISTS (SELECT 1 FROM enterprise_contract_versions v
            WHERE v.contract_id=NEW.contract_id)) THEN
      RAISE EXCEPTION USING ERRCODE='23514',
        MESSAGE='contract version lacks staff authority, its contract, or a valid term relation';
    END IF;
    RETURN NEW;
  END IF;
  IF NEW.id IS DISTINCT FROM OLD.id OR NEW.contract_id IS DISTINCT FROM OLD.contract_id
    OR NEW.billing_account_id IS DISTINCT FROM OLD.billing_account_id
    OR NEW.version_number IS DISTINCT FROM OLD.version_number OR NEW.version_kind IS DISTINCT FROM OLD.version_kind
    OR NEW.term_version_id IS DISTINCT FROM OLD.term_version_id OR NEW.interval IS DISTINCT FROM OLD.interval
    OR NEW.term_starts_at IS DISTINCT FROM OLD.term_starts_at OR NEW.term_ends_at IS DISTINCT FROM OLD.term_ends_at
    OR NEW.effective_at IS DISTINCT FROM OLD.effective_at OR NEW.currency IS DISTINCT FROM OLD.currency
    OR NEW.price_minor IS DISTINCT FROM OLD.price_minor
    OR NEW.monthly_credit_amount IS DISTINCT FROM OLD.monthly_credit_amount
    OR NEW.committed_seats IS DISTINCT FROM OLD.committed_seats
    OR NEW.capabilities_json::text IS DISTINCT FROM OLD.capabilities_json::text
    OR NEW.exclusivity_key IS DISTINCT FROM OLD.exclusivity_key OR NEW.renewal_mode IS DISTINCT FROM OLD.renewal_mode
    OR NEW.executed_reference IS DISTINCT FROM OLD.executed_reference
    OR NEW.executed_evidence_reference IS DISTINCT FROM OLD.executed_evidence_reference
    OR NEW.recorded_by_user_id IS DISTINCT FROM OLD.recorded_by_user_id
    OR NEW.recorded_permission_grant_id IS DISTINCT FROM OLD.recorded_permission_grant_id
    OR NEW.request_fingerprint IS DISTINCT FROM OLD.request_fingerprint
    OR NEW.idempotency_registry_id IS DISTINCT FROM OLD.idempotency_registry_id
    OR NEW.recorded_at IS DISTINCT FROM OLD.recorded_at THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='executed contract terms and evidence are immutable';
  END IF;
  IF (NEW.entitlement_definition_id IS DISTINCT FROM OLD.entitlement_definition_id
      OR NEW.subscription_id IS DISTINCT FROM OLD.subscription_id
      OR NEW.entitlement_instance_id IS DISTINCT FROM OLD.entitlement_instance_id)
    AND NOT (OLD.state='recorded' AND NEW.state='approved' AND OLD.subscription_id IS NULL
             AND OLD.entitlement_definition_id IS NULL AND OLD.entitlement_instance_id IS NULL) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='a version binds its term once, at approval';
  END IF;
  -- B1: verified payment evidence is never discarded with its version.
  IF NEW.state IN ('cancelled','superseded') AND EXISTS (
       SELECT 1 FROM enterprise_contract_term_fundings f WHERE f.version_id=NEW.id) THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='a funded contract version cannot be cancelled; it awaits activation or a refund decision';
  END IF;
  IF NEW.state IS DISTINCT FROM OLD.state OR NEW.last_event_id IS DISTINCT FROM OLD.last_event_id THEN
    SELECT * INTO e FROM enterprise_contract_events WHERE id=NEW.last_event_id;
    IF e.id IS NULL OR NEW.last_event_id IS NOT DISTINCT FROM OLD.last_event_id OR e.version_id<>NEW.id
      OR e.scope<>'version' OR e.from_state<>OLD.state OR e.to_state<>NEW.state THEN
      RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='contract version state changes require an append-only event';
    END IF;
    IF NEW.state='active' AND NOT EXISTS (SELECT 1 FROM enterprise_contract_activations a WHERE a.version_id=NEW.id) THEN
      RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='a contract version becomes active only through its activation';
    END IF;
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE FUNCTION phase11_event_guard() RETURNS trigger AS $$
DECLARE c enterprise_contracts%ROWTYPE; v enterprise_contract_versions%ROWTYPE;
BEGIN
  PERFORM phase11_require_read_committed();
  SELECT * INTO c FROM enterprise_contracts WHERE id=NEW.contract_id;
  IF NEW.version_id IS NOT NULL THEN SELECT * INTO v FROM enterprise_contract_versions WHERE id=NEW.version_id; END IF;
  IF c.id IS NULL OR (NEW.version_id IS NOT NULL AND (v.id IS NULL OR v.contract_id<>c.id))
    OR NEW.from_state<>(CASE WHEN NEW.version_id IS NULL THEN c.state ELSE v.state END)
    OR NOT phase11_grant_ok(NEW.permission_grant_id, NEW.actor_user_id)
    OR NOT phase11_claimed(NEW.idempotency_registry_id, 'enterprise_contract_command')
    OR NOT phase11_event_ok(NEW.domain_event_id, c.billing_account_id, 'enterprise_contract_' || NEW.transition, NEW.id)
  THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='contract event lacks staff authority or communication evidence'; END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE FUNCTION phase11_funding_guard() RETURNS trigger AS $$
DECLARE v enterprise_contract_versions%ROWTYPE; l financial_lines%ROWTYPE; t financial_transactions%ROWTYPE;
        i external_event_inbox%ROWTYPE;
BEGIN
  PERFORM phase11_require_read_committed();
  -- FOR SHARE serializes with a concurrent cancellation of the same version.
  SELECT * INTO v FROM enterprise_contract_versions WHERE id=NEW.version_id FOR SHARE;
  SELECT * INTO l FROM financial_lines WHERE id=NEW.financial_line_id;
  SELECT * INTO t FROM financial_transactions WHERE id=l.financial_transaction_id;
  SELECT * INTO i FROM external_event_inbox WHERE id=t.inbox_event_id;
  IF v.id IS NULL OR l.id IS NULL OR t.id IS NULL OR i.id IS NULL
    OR v.state<>'approved' OR v.contract_id<>NEW.contract_id OR v.billing_account_id<>NEW.billing_account_id
    OR v.subscription_id IS DISTINCT FROM NEW.subscription_id OR t.id<>NEW.financial_transaction_id
    OR t.billing_account_id<>NEW.billing_account_id OR t.kind<>'payment' OR t.provider<>'stripe'
    OR i.provider<>'stripe' OR i.state='quarantined' OR t.principal_minor<=0
    OR l.subscription_id IS DISTINCT FROM v.subscription_id
    OR l.line_kind<>(CASE WHEN v.version_kind='amendment' THEN 'seat' ELSE 'subscription' END)
    OR (v.version_kind<>'amendment' AND l.entitlement_instance_id IS DISTINCT FROM v.entitlement_instance_id)
    OR l.currency<>v.currency OR t.currency<>v.currency OR NEW.currency<>v.currency
    OR l.principal_minor<=0 OR l.discount_minor>0 OR l.principal_minor+l.discount_minor<>v.price_minor
    OR NEW.amount_minor<>v.price_minor OR NEW.paid_at<>t.effective_at
    OR NOT phase11_grant_ok(NEW.permission_grant_id, NEW.actor_user_id)
    OR NOT phase11_claimed(NEW.idempotency_registry_id, 'enterprise_contract_command')
    OR NOT phase11_event_ok(NEW.domain_event_id, NEW.billing_account_id, 'enterprise_contract_funded', NEW.id)
  THEN RAISE EXCEPTION USING ERRCODE='23514',
    MESSAGE='contract funding requires a verified Stripe payment of the exact agreed amount'; END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE FUNCTION phase11_activation_guard() RETURNS trigger AS $$
DECLARE v enterprise_contract_versions%ROWTYPE; f enterprise_contract_term_fundings%ROWTYPE;
BEGIN
  PERFORM phase11_require_read_committed();
  SELECT * INTO v FROM enterprise_contract_versions WHERE id=NEW.version_id;
  SELECT * INTO f FROM enterprise_contract_term_fundings WHERE id=NEW.term_funding_id;
  IF v.id IS NULL OR f.id IS NULL OR v.state<>'approved' OR f.version_id<>v.id
    OR v.contract_id<>NEW.contract_id OR v.billing_account_id<>NEW.billing_account_id
    OR v.subscription_id IS DISTINCT FROM NEW.subscription_id OR NEW.seats<>v.committed_seats
    OR now()<v.effective_at OR clock_timestamp()<v.effective_at OR NEW.activated_at<>now()
    OR (v.version_kind<>'amendment' AND (NEW.entitlement_instance_id IS DISTINCT FROM v.entitlement_instance_id
        OR clock_timestamp()>=v.term_ends_at OR clock_timestamp()>=phase4_add_months(v.term_starts_at, 1)))
    OR (v.version_kind='renewal' AND f.paid_at>=v.term_starts_at + interval '15 days')
    OR (v.version_kind='amendment' AND NEW.entitlement_instance_id IS NOT NULL)
    OR NOT phase11_grant_ok(NEW.permission_grant_id, NEW.actor_user_id)
    OR NOT phase11_claimed(NEW.idempotency_registry_id, 'enterprise_contract_command')
    OR NOT phase11_event_ok(NEW.domain_event_id, NEW.billing_account_id, 'enterprise_contract_activated', NEW.id)
  THEN RAISE EXCEPTION USING ERRCODE='23514',
    MESSAGE='contract activation requires an approved, effective, fully funded version'; END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE FUNCTION phase11_notice_guard() RETURNS trigger AS $$
DECLARE v enterprise_contract_versions%ROWTYPE; prior enterprise_contract_notices%ROWTYPE;
BEGIN
  PERFORM phase11_require_read_committed();
  SELECT * INTO v FROM enterprise_contract_versions WHERE id=NEW.term_version_id;
  IF v.id IS NULL OR v.contract_id<>NEW.contract_id OR v.version_kind NOT IN ('initial','renewal')
    OR NEW.received_at<>now() OR NEW.deadline_at<>v.term_ends_at - interval '30 days'
    OR NEW.timely IS DISTINCT FROM (now()<=NEW.deadline_at)
    OR NOT phase11_grant_ok(NEW.permission_grant_id, NEW.actor_user_id)
    OR NOT phase11_claimed(NEW.idempotency_registry_id, 'enterprise_contract_command')
  THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='nonrenewal notice lacks authority or a valid deadline'; END IF;
  IF NEW.kind='nonrenewal_reversal' THEN
    SELECT * INTO prior FROM enterprise_contract_notices WHERE id=NEW.reverses_notice_id;
    IF prior.id IS NULL OR prior.kind<>'nonrenewal' OR NOT prior.timely OR prior.term_version_id<>NEW.term_version_id
      OR clock_timestamp()>prior.deadline_at THEN
      RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='only an effective notice can be reversed before its deadline';
    END IF;
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

-- Enterprise entitlements leave ``proposed`` only through a Phase 11
-- activation and expire only at or after their term end.
CREATE FUNCTION phase11_entitlement_event_guard() RETURNS trigger AS $$
DECLARE inst entitlement_instances%ROWTYPE;
BEGIN
  SELECT * INTO inst FROM entitlement_instances WHERE id=NEW.entitlement_instance_id;
  IF inst.source_type<>'enterprise_contract' THEN RETURN NEW; END IF;
  IF NEW.from_state='proposed' AND NEW.to_state='scheduled' AND NOT EXISTS (
       SELECT 1 FROM enterprise_contract_activations a JOIN enterprise_contract_versions v ON v.id=a.version_id
       WHERE a.entitlement_instance_id=inst.id AND v.entitlement_instance_id=inst.id AND v.id=inst.source_id
         AND v.state='approved' AND a.subscription_id=inst.subscription_id) THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='Enterprise entitlements require Phase 11 contract activation evidence';
  END IF;
  IF NEW.from_state='active' AND NEW.to_state='expired'
     AND (NEW.effective_at < inst.ends_at OR now() < inst.ends_at) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Enterprise entitlement cannot expire before its term ends';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE FUNCTION phase11_contract_commitment_guard() RETURNS trigger AS $$
DECLARE s billing_subscriptions%ROWTYPE; previous seat_commitments%ROWTYPE;
BEGIN
  PERFORM phase8_flip_fence(NEW.subscription_id);
  SELECT * INTO s FROM billing_subscriptions WHERE id=NEW.subscription_id FOR SHARE;
  IF s.id IS NULL OR s.processor<>{CONTRACT} OR s.billing_account_id<>NEW.billing_account_id
    OR s.state NOT IN ('active','past_due') OR NEW.state<>'active' OR NEW.ends_at IS NOT NULL
    OR NOT phase11_claimed(NEW.idempotency_registry_id, 'enterprise_contract_seat')
    OR NOT phase8_event_ok(NEW.domain_event_id, NEW.billing_account_id, 'seat_commitment_contracted',
         'seat_commitment', NEW.id)
    OR NOT EXISTS (SELECT 1 FROM enterprise_contract_activations a WHERE a.seat_commitment_id=NEW.id
         AND a.subscription_id=NEW.subscription_id AND a.seats=NEW.quantity) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='contracted seats require their contract activation';
  END IF;
  IF NEW.previous_commitment_id IS NULL THEN
    IF EXISTS (SELECT 1 FROM seat_commitments c WHERE c.subscription_id=NEW.subscription_id AND c.id<>NEW.id) THEN
      RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='a contract term opens its seat commitment once';
    END IF;
  ELSE
    SELECT * INTO previous FROM seat_commitments WHERE id=NEW.previous_commitment_id;
    IF previous.id IS NULL OR previous.subscription_id<>NEW.subscription_id OR previous.state<>'replaced'
      OR previous.ends_at<>NEW.starts_at OR NEW.quantity<=previous.quantity THEN
      RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='contracted seats never fall mid-term';
    END IF;
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE FUNCTION phase11_contract_commitment_final() RETURNS trigger AS $$
DECLARE c seat_commitments%ROWTYPE;
BEGIN
  SELECT * INTO c FROM seat_commitments WHERE id=NEW.id;
  IF c.state='replaced' AND NOT EXISTS (
      SELECT 1 FROM seat_commitments n WHERE n.previous_commitment_id=c.id AND n.starts_at=c.ends_at) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='a closed seat commitment requires its successor';
  END IF;
  IF NOT EXISTS (SELECT 1 FROM enterprise_contract_activations a WHERE a.seat_commitment_id=c.id) THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='contracted seats require their contract activation';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE FUNCTION phase11_reject_contract_backed() RETURNS trigger AS $$
BEGIN
  IF EXISTS (SELECT 1 FROM billing_subscriptions s WHERE s.id=NEW.subscription_id AND s.processor={CONTRACT}) THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='contract-backed terms change only through an Enterprise contract version';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE FUNCTION phase11_purchase_expiration_guard() RETURNS trigger AS $$
DECLARE lot_row credit_lots%ROWTYPE;
BEGIN
  SELECT * INTO lot_row FROM credit_lots WHERE id=NEW.lot_id;
  IF lot_row.source_type<>'credit_pack_purchase' THEN RETURN NEW; END IF;
  IF lot_row.expires_at IS NULL OR now()<lot_row.expires_at OR NEW.effective_at<>lot_row.expires_at
    OR NOT EXISTS (SELECT 1 FROM domain_events e JOIN communication_outbox o ON o.domain_event_id=e.id
         WHERE e.billing_account_id=NEW.billing_account_id AND e.event_type='credits_expired'
           AND e.event_key='credits_expired:purchase:' || lot_row.source_id) THEN
    RAISE EXCEPTION USING ERRCODE='23514',
      MESSAGE='purchased credit expires only at its paid term end, with communication evidence';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE FUNCTION phase11_purchase_expiration_final() RETURNS trigger AS $$
DECLARE lot_row credit_lots%ROWTYPE; available_total bigint; held_total bigint;
BEGIN
  SELECT * INTO lot_row FROM credit_lots WHERE id=NEW.lot_id;
  IF lot_row.source_type<>'credit_pack_purchase' THEN RETURN NEW; END IF;
  SELECT COALESCE(sum(available_delta),0), COALESCE(sum(held_delta),0) INTO available_total, held_total
    FROM credit_ledger_entries WHERE lot_id=lot_row.id;
  IF available_total<>0 OR held_total<>0 THEN
    RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='purchased-credit expiration must expire all remaining value';
  END IF;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_phase11_contract_guard BEFORE INSERT OR UPDATE OR DELETE ON enterprise_contracts
  FOR EACH ROW EXECUTE FUNCTION phase11_contract_guard();
CREATE TRIGGER trg_phase11_version_guard BEFORE INSERT OR UPDATE OR DELETE ON enterprise_contract_versions
  FOR EACH ROW EXECUTE FUNCTION phase11_version_guard();
CREATE TRIGGER trg_phase11_event_guard BEFORE INSERT ON enterprise_contract_events
  FOR EACH ROW EXECUTE FUNCTION phase11_event_guard();
CREATE TRIGGER trg_phase11_funding_guard BEFORE INSERT ON enterprise_contract_term_fundings
  FOR EACH ROW EXECUTE FUNCTION phase11_funding_guard();
CREATE TRIGGER trg_phase11_activation_guard BEFORE INSERT ON enterprise_contract_activations
  FOR EACH ROW EXECUTE FUNCTION phase11_activation_guard();
CREATE TRIGGER trg_phase11_notice_guard BEFORE INSERT ON enterprise_contract_notices
  FOR EACH ROW EXECUTE FUNCTION phase11_notice_guard();
CREATE TRIGGER trg_phase11_entitlement_event_guard BEFORE INSERT ON entitlement_events
  FOR EACH ROW EXECUTE FUNCTION phase11_entitlement_event_guard();
CREATE TRIGGER trg_phase11_contract_commitment_guard BEFORE INSERT ON seat_commitments
  FOR EACH ROW WHEN (NEW.origin_type = 'contract') EXECUTE FUNCTION phase11_contract_commitment_guard();
CREATE CONSTRAINT TRIGGER trg_phase11_contract_commitment_final AFTER INSERT OR UPDATE ON seat_commitments
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.origin_type = 'contract')
  EXECUTE FUNCTION phase11_contract_commitment_final();
CREATE TRIGGER trg_phase11_commitment_contract_refused BEFORE INSERT ON seat_commitments
  FOR EACH ROW WHEN (NEW.origin_type <> 'contract') EXECUTE FUNCTION phase11_reject_contract_backed();
CREATE TRIGGER trg_phase11_purchase_expiration_guard BEFORE INSERT ON credit_ledger_entries
  FOR EACH ROW WHEN (NEW.entry_type = 'expiration') EXECUTE FUNCTION phase11_purchase_expiration_guard();
CREATE CONSTRAINT TRIGGER trg_phase11_purchase_expiration_final AFTER INSERT ON credit_ledger_entries
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.entry_type = 'expiration')
  EXECUTE FUNCTION phase11_purchase_expiration_final();

-- Phase 8 keeps guarding every non-contract commitment exactly as before.
DROP TRIGGER trg_phase8_commitment_guard ON seat_commitments;
CREATE TRIGGER trg_phase8_commitment_guard BEFORE UPDATE OR DELETE ON seat_commitments
  FOR EACH ROW EXECUTE FUNCTION phase8_commitment_guard();
CREATE TRIGGER trg_phase8_commitment_insert_guard BEFORE INSERT ON seat_commitments
  FOR EACH ROW WHEN (NEW.origin_type <> 'contract') EXECUTE FUNCTION phase8_commitment_guard();
DROP TRIGGER trg_phase8_commitment_final ON seat_commitments;
CREATE CONSTRAINT TRIGGER trg_phase8_commitment_final AFTER INSERT OR UPDATE ON seat_commitments
  DEFERRABLE INITIALLY DEFERRED FOR EACH ROW WHEN (NEW.origin_type <> 'contract')
  EXECUTE FUNCTION phase8_commitment_final();
"""

PG_TRIGGERS = (
    ("trg_phase11_contract_guard", "enterprise_contracts"),
    ("trg_phase11_version_guard", "enterprise_contract_versions"),
    ("trg_phase11_event_guard", "enterprise_contract_events"),
    ("trg_phase11_funding_guard", "enterprise_contract_term_fundings"),
    ("trg_phase11_activation_guard", "enterprise_contract_activations"),
    ("trg_phase11_notice_guard", "enterprise_contract_notices"),
    ("trg_phase11_entitlement_event_guard", "entitlement_events"),
    ("trg_phase11_contract_commitment_guard", "seat_commitments"),
    ("trg_phase11_contract_commitment_final", "seat_commitments"),
    ("trg_phase11_commitment_contract_refused", "seat_commitments"),
    ("trg_phase11_purchase_expiration_guard", "credit_ledger_entries"),
    ("trg_phase11_purchase_expiration_final", "credit_ledger_entries"),
) + tuple((f"trg_phase11_{table}_contract_refused", table) for table in CONTRACT_REFUSED_TABLES) + tuple(
    (f"trg_phase11_{table}_{suffix}", table)
    for table in TABLES for suffix in ("immutable", "no_truncate")
)
PG_FUNCTIONS = (
    "phase11_purchase_expiration_final()", "phase11_purchase_expiration_guard()",
    "phase11_reject_contract_backed()", "phase11_contract_commitment_final()",
    "phase11_contract_commitment_guard()", "phase11_entitlement_event_guard()", "phase11_notice_guard()",
    "phase11_activation_guard()", "phase11_funding_guard()", "phase11_event_guard()",
    "phase11_version_guard()", "phase11_contract_guard()", "phase11_reject_truncate()",
    "phase11_reject_row_change()", "phase11_claimed(text, text)",
    "phase11_event_ok(text, text, text, text)", "phase11_grant_ok(text, text)",
    "phase11_require_read_committed()",
)
IMMUTABLE_TABLES = (
    "enterprise_contract_events", "enterprise_contract_term_fundings",
    "enterprise_contract_activations", "enterprise_contract_notices",
)


def _postgresql_guards():
    op.execute(_PG_PHASE11)
    for table in IMMUTABLE_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_phase11_{table}_immutable BEFORE UPDATE OR DELETE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION phase11_reject_row_change()"
        )
    for table in TABLES:
        op.execute(
            f"CREATE TRIGGER trg_phase11_{table}_no_truncate BEFORE TRUNCATE ON {table} "
            "FOR EACH STATEMENT EXECUTE FUNCTION phase11_reject_truncate()"
        )
    for table in CONTRACT_REFUSED_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_phase11_{table}_contract_refused BEFORE INSERT ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION phase11_reject_contract_backed()"
        )
    for statement in _pg_replacements(_pg_originals()).values():
        op.execute(statement)


# ---------------------------------------------------------------------------
# SQLite guards (development parity; PostgreSQL is the acceptance target)
# ---------------------------------------------------------------------------

def _sqlite_statements():
    statements = []
    for table in IMMUTABLE_TABLES:
        for action in ("update", "delete"):
            statements.append(
                f"CREATE TRIGGER trg_phase11_{table}_{action} BEFORE {action.upper()} ON {table} "
                "BEGIN SELECT RAISE(ABORT,'Phase 11 contract evidence is immutable'); END"
            )
    for table in ("enterprise_contracts", "enterprise_contract_versions"):
        statements.append(
            f"CREATE TRIGGER trg_phase11_{table}_delete BEFORE DELETE ON {table} "
            "BEGIN SELECT RAISE(ABORT,'contracts are historical records'); END"
        )
    statements += [
        "CREATE TRIGGER trg_phase11_contract_state_update BEFORE UPDATE ON enterprise_contracts "
        "WHEN NEW.id IS NOT OLD.id OR NEW.billing_account_id IS NOT OLD.billing_account_id "
        "OR NEW.contract_reference IS NOT OLD.contract_reference "
        "OR ((NEW.state IS NOT OLD.state OR NEW.last_event_id IS NOT OLD.last_event_id) AND NOT EXISTS ("
        "SELECT 1 FROM enterprise_contract_events e WHERE e.id=NEW.last_event_id AND NEW.last_event_id IS NOT OLD.last_event_id "
        "AND e.contract_id=NEW.id AND e.scope='contract' AND e.from_state=OLD.state AND e.to_state=NEW.state)) "
        "BEGIN SELECT RAISE(ABORT,'contract state changes require an append-only event'); END",
        "CREATE TRIGGER trg_phase11_version_update BEFORE UPDATE ON enterprise_contract_versions "
        "WHEN NEW.id IS NOT OLD.id OR NEW.contract_id IS NOT OLD.contract_id OR NEW.version_kind IS NOT OLD.version_kind "
        "OR NEW.price_minor IS NOT OLD.price_minor OR NEW.committed_seats IS NOT OLD.committed_seats "
        "OR NEW.monthly_credit_amount IS NOT OLD.monthly_credit_amount OR NEW.term_starts_at IS NOT OLD.term_starts_at "
        "OR NEW.term_ends_at IS NOT OLD.term_ends_at OR NEW.effective_at IS NOT OLD.effective_at "
        "OR NEW.executed_reference IS NOT OLD.executed_reference "
        "OR ((NEW.state IS NOT OLD.state OR NEW.last_event_id IS NOT OLD.last_event_id) AND NOT EXISTS ("
        "SELECT 1 FROM enterprise_contract_events e WHERE e.id=NEW.last_event_id AND NEW.last_event_id IS NOT OLD.last_event_id "
        "AND e.version_id=NEW.id AND e.scope='version' AND e.from_state=OLD.state AND e.to_state=NEW.state)) "
        "BEGIN SELECT RAISE(ABORT,'executed contract terms are immutable and state changes require an event'); END",
        "CREATE TRIGGER trg_phase11_funded_version_cancel BEFORE UPDATE ON enterprise_contract_versions "
        "WHEN NEW.state IN ('cancelled','superseded') AND EXISTS (SELECT 1 FROM enterprise_contract_term_fundings f "
        "WHERE f.version_id=NEW.id) "
        "BEGIN SELECT RAISE(ABORT,'a funded contract version cannot be cancelled; it awaits activation or a refund decision'); END",
        "CREATE TRIGGER trg_phase11_entitlement_event_insert BEFORE INSERT ON entitlement_events "
        "WHEN NEW.from_state='proposed' AND NEW.to_state='scheduled' AND EXISTS (SELECT 1 FROM entitlement_instances i "
        "WHERE i.id=NEW.entitlement_instance_id AND i.source_type='enterprise_contract') "
        "AND NOT EXISTS (SELECT 1 FROM enterprise_contract_activations a JOIN entitlement_instances i "
        "ON i.id=a.entitlement_instance_id WHERE i.id=NEW.entitlement_instance_id AND a.subscription_id=i.subscription_id) "
        "BEGIN SELECT RAISE(ABORT,'Enterprise entitlements require Phase 11 contract activation evidence'); END",
        "CREATE TRIGGER trg_phase11_contract_commitment_insert BEFORE INSERT ON seat_commitments "
        "WHEN NEW.origin_type='contract' AND NOT EXISTS (SELECT 1 FROM enterprise_contract_activations a "
        "JOIN billing_subscriptions s ON s.id=a.subscription_id WHERE a.seat_commitment_id=NEW.id "
        f"AND a.subscription_id=NEW.subscription_id AND a.seats=NEW.quantity AND s.processor={CONTRACT}) "
        "BEGIN SELECT RAISE(ABORT,'contracted seats require their contract activation'); END",
        "CREATE TRIGGER trg_phase11_commitment_contract_refused BEFORE INSERT ON seat_commitments "
        "WHEN NEW.origin_type<>'contract' AND EXISTS (SELECT 1 FROM billing_subscriptions s "
        f"WHERE s.id=NEW.subscription_id AND s.processor={CONTRACT}) "
        "BEGIN SELECT RAISE(ABORT,'contract-backed terms change only through an Enterprise contract version'); END",
        "CREATE TRIGGER trg_phase11_purchase_expiration_insert BEFORE INSERT ON credit_ledger_entries "
        "WHEN NEW.entry_type='expiration' AND (SELECT source_type FROM credit_lots WHERE id=NEW.lot_id)='credit_pack_purchase' "
        "AND ((SELECT expires_at FROM credit_lots WHERE id=NEW.lot_id) IS NULL "
        "OR julianday(CURRENT_TIMESTAMP)<julianday((SELECT expires_at FROM credit_lots WHERE id=NEW.lot_id))) "
        "BEGIN SELECT RAISE(ABORT,'purchased credit expires only at its paid term end'); END",
    ]
    for table in CONTRACT_REFUSED_TABLES:
        statements.append(
            f"CREATE TRIGGER trg_phase11_{table}_contract_refused BEFORE INSERT ON {table} "
            f"WHEN EXISTS (SELECT 1 FROM billing_subscriptions s WHERE s.id=NEW.subscription_id AND s.processor={CONTRACT}) "
            "BEGIN SELECT RAISE(ABORT,'contract-backed terms change only through an Enterprise contract version'); END"
        )
    return statements


def _sqlite_trigger_names():
    return [re.match(r"CREATE TRIGGER (\S+)", statement).group(1) for statement in _sqlite_statements()]


def _sqlite_guards():
    for statement in _sqlite_statements():
        op.execute(statement)
    for name, statement in _sqlite_replacements(_sqlite_originals()).items():
        op.execute(f"DROP TRIGGER IF EXISTS {name}")
        op.execute(statement)


# ---------------------------------------------------------------------------
# Upgrade / downgrade
# ---------------------------------------------------------------------------

def upgrade():
    _create_tables()
    _replace_checks(forward=True)
    if op.get_bind().dialect.name == "postgresql":
        _postgresql_guards()
    else:
        _sqlite_guards()


def downgrade():
    bind = op.get_bind()
    pg = bind.dialect.name == "postgresql"
    if pg:
        for table in TABLES:
            op.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
        for table in ("credit_lots", "credit_purchase_fundings", "entitlement_instances", "seat_commitments"):
            op.execute(sa.text(f"LOCK TABLE {table} IN SHARE ROW EXCLUSIVE MODE"))
    for table in TABLES:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None:
            raise Phase11EvidenceNotEmptyError("Phase 11 downgrade refuses to discard contract evidence")
    refusals = (
        ("SELECT 1 FROM credit_purchase_fundings WHERE expires_at IS NOT NULL LIMIT 1",
         "Phase 11 downgrade refuses to discard credit-pack term expiry evidence"),
        ("SELECT 1 FROM credit_lots l JOIN credit_periods p ON p.id=l.source_id "
         "WHERE l.source_type='subscription_recurring' AND l.expires_at<>p.ends_at LIMIT 1",
         "Phase 11 downgrade refuses to re-tighten annual lots that already run to their term end"),
        ("SELECT 1 FROM credit_lots l JOIN upgrade_credit_allocations a ON a.id=l.source_id "
         "WHERE l.source_type='subscription_recurring' AND l.expires_at<>a.period_ends_at LIMIT 1",
         "Phase 11 downgrade refuses to re-tighten annual proration lots that run to their term end"),
        ("SELECT 1 FROM entitlement_instances WHERE source_type='enterprise_contract' LIMIT 1",
         "Phase 11 downgrade refuses to re-gate Enterprise entitlements"),
        ("SELECT 1 FROM billing_staff_permission_grants WHERE permission='billing.enterprise_contract.manage' LIMIT 1",
         "Phase 11 downgrade refuses to discard Enterprise contract permission grants"),
        ("SELECT 1 FROM seat_commitments WHERE origin_type='contract' LIMIT 1",
         "Phase 11 downgrade refuses to discard contracted seat commitments"),
    )
    for query, message in refusals:
        if bind.execute(sa.text(query)).first() is not None:
            raise Phase11EvidenceNotEmptyError(message)
    if pg:
        op.execute("DROP TRIGGER IF EXISTS trg_phase8_commitment_insert_guard ON seat_commitments")
        op.execute("DROP TRIGGER IF EXISTS trg_phase8_commitment_guard ON seat_commitments")
        op.execute(
            "CREATE TRIGGER trg_phase8_commitment_guard BEFORE INSERT OR UPDATE OR DELETE ON seat_commitments "
            "FOR EACH ROW EXECUTE FUNCTION phase8_commitment_guard()"
        )
        op.execute("DROP TRIGGER IF EXISTS trg_phase8_commitment_final ON seat_commitments")
        op.execute(
            "CREATE CONSTRAINT TRIGGER trg_phase8_commitment_final AFTER INSERT OR UPDATE ON seat_commitments "
            "DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION phase8_commitment_final()"
        )
        for trigger, table in PG_TRIGGERS:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))
        for function in PG_FUNCTIONS:
            op.execute(sa.text(f"DROP FUNCTION IF EXISTS {function}"))
        for statement in _pg_originals().values():
            op.execute(statement)
    else:
        for name in _sqlite_trigger_names():
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {name}"))
        originals = _sqlite_originals()
        for name in originals:
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
        # SQLite cannot drop a column that carries a foreign key in place. A
        # batch rebuild drops the table's own triggers and fails while another
        # trigger names the table, so rebuild first, then restore every
        # affected trigger verbatim from its own revision.
        op.drop_index("ix_credit_purchase_fundings_expiry_subscription", table_name="credit_purchase_fundings")
        with op.batch_alter_table("credit_purchase_fundings", recreate="always") as batch:
            batch.drop_column("expires_at")
            batch.drop_column("expiry_subscription_id")
        phase9 = _captured("e1a3c5b7d9f2_add_financial_effects", "_sqlite_guards")
        for name in ("trg_phase9_credit_purchase_fundings_update", "trg_phase9_credit_purchase_fundings_delete"):
            op.execute(f"DROP TRIGGER IF EXISTS {name}")
            op.execute(re.search(r"CREATE TRIGGER " + name + r"\b.*?END", phase9, re.S).group(0))
        for statement in originals.values():
            op.execute(statement)
    _replace_checks(forward=False)
    if pg:
        op.drop_index("ix_credit_purchase_fundings_expiry_subscription", table_name="credit_purchase_fundings")
        op.drop_column("credit_purchase_fundings", "expires_at")
        op.drop_column("credit_purchase_fundings", "expiry_subscription_id")
    for index, table in (
        ("ix_enterprise_contract_notices_term", "enterprise_contract_notices"),
        ("ix_enterprise_contract_activations_subscription", "enterprise_contract_activations"),
        ("ix_enterprise_contract_term_fundings_subscription", "enterprise_contract_term_fundings"),
        ("ix_enterprise_contract_events_contract", "enterprise_contract_events"),
        ("ix_enterprise_contract_versions_term", "enterprise_contract_versions"),
        ("ix_enterprise_contract_versions_contract_state", "enterprise_contract_versions"),
        ("ix_enterprise_contracts_account_state", "enterprise_contracts"),
    ):
        op.drop_index(index, table_name=table)
    for table in TABLES:
        op.drop_table(table)
