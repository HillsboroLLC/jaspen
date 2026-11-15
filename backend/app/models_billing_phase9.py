"""Inactive Phase 9 purchase-funding and financial-case credit-effect evidence.

Nothing in live routes, webhooks, jobs, or readers writes to or reads from
these tables. Phase 3 remains the only credit ledger; these rows are immutable
provenance that binds each Phase 3 effect to its Phase 5.2 financial source and
Phase 5.3 case version.
"""

import uuid

from . import db


FUNDING_KINDS = ("credit_purchase", "recurring_allocation", "upgrade_allocation")
CREDIT_EFFECT_TYPES = ("hold", "release", "reversal", "recovery")


def _quoted(values):
    return ", ".join(f"'{value}'" for value in values)


class CreditPurchaseFunding(db.Model):
    """Immutable proof that one paid credit-pack line funded one package component."""

    __tablename__ = "credit_purchase_fundings"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    billing_account_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_accounts.id", name="fk_credit_purchase_fundings_account", ondelete="RESTRICT"),
        nullable=False,
    )
    financial_transaction_id = db.Column(
        db.String(36),
        db.ForeignKey("financial_transactions.id", name="fk_credit_purchase_fundings_transaction", ondelete="RESTRICT"),
        nullable=False,
    )
    financial_line_id = db.Column(
        db.String(36),
        db.ForeignKey("financial_lines.id", name="fk_credit_purchase_fundings_line", ondelete="RESTRICT"),
        nullable=False,
    )
    entitlement_definition_id = db.Column(
        db.String(36),
        db.ForeignKey("entitlement_definitions.id", name="fk_credit_purchase_fundings_definition", ondelete="RESTRICT"),
        nullable=False,
    )
    package_component = db.Column(db.String(64), nullable=False)
    funding_key = db.Column(db.String(512), nullable=False)
    request_fingerprint = db.Column(db.String(64), nullable=False)
    credit_amount = db.Column(db.BigInteger, nullable=False)
    paid_at = db.Column(db.DateTime(timezone=True), nullable=False)
    lot_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "credit_lots.id", name="fk_credit_purchase_fundings_lot", ondelete="RESTRICT",
            deferrable=True, initially="DEFERRED",
        ),
        nullable=False,
    )
    grant_entry_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "credit_ledger_entries.id", name="fk_credit_purchase_fundings_grant", ondelete="RESTRICT",
            deferrable=True, initially="DEFERRED",
        ),
        nullable=False,
    )
    idempotency_registry_id = db.Column(
        db.String(36),
        db.ForeignKey("idempotency_registry.id", name="fk_credit_purchase_fundings_registry", ondelete="RESTRICT"),
        nullable=False,
    )
    domain_event_id = db.Column(
        db.String(36),
        db.ForeignKey("domain_events.id", name="fk_credit_purchase_fundings_domain_event", ondelete="RESTRICT"),
        nullable=False,
    )
    contract_version = db.Column(db.Integer, nullable=False)
    actor_type = db.Column(db.String(40), nullable=False)
    actor_id = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())
    # Phase 11 credit-pack policy: a pack expires at the end of the paid term
    # (monthly or annual) in force when it was paid. These columns record that
    # binding; database guards require both and match them to the term.
    expiry_subscription_id = db.Column(
        db.String(36),
        db.ForeignKey(
            "billing_subscriptions.id", name="fk_credit_purchase_fundings_expiry_subscription",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    expires_at = db.Column(db.DateTime(timezone=True), nullable=True)

    __table_args__ = (
        db.CheckConstraint("credit_amount > 0", name="ck_credit_purchase_fundings_amount"),
        db.CheckConstraint("contract_version = 1", name="ck_credit_purchase_fundings_contract"),
        db.CheckConstraint(
            "length(trim(package_component)) > 0 AND length(trim(funding_key)) > 0 "
            "AND length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint) "
            "AND funding_key = 'purchase:' || financial_line_id || ':' || package_component "
            "AND length(trim(actor_type)) > 0 AND length(trim(actor_id)) > 0",
            name="ck_credit_purchase_fundings_identity",
        ),
        db.UniqueConstraint("funding_key", name="uq_credit_purchase_fundings_key"),
        db.UniqueConstraint(
            "financial_line_id", "package_component",
            name="uq_credit_purchase_fundings_line_component",
        ),
        db.UniqueConstraint("lot_id", name="uq_credit_purchase_fundings_lot"),
        db.UniqueConstraint("grant_entry_id", name="uq_credit_purchase_fundings_grant"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_credit_purchase_fundings_registry"),
        db.Index("ix_credit_purchase_fundings_account_paid", "billing_account_id", "paid_at", "id"),
        db.Index("ix_credit_purchase_fundings_domain_event", "domain_event_id"),
        db.Index("ix_credit_purchase_fundings_expiry_subscription", "expiry_subscription_id"),
    )


class FinancialCaseLotEvaluation(db.Model):
    """Immutable D10 calculation for one accepted case version and one funded lot."""

    __tablename__ = "financial_case_lot_evaluations"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    billing_account_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_accounts.id", name="fk_financial_case_lot_evaluations_account", ondelete="RESTRICT"),
        nullable=False,
    )
    financial_case_id = db.Column(
        db.String(36),
        db.ForeignKey("financial_cases.id", name="fk_financial_case_lot_evaluations_case", ondelete="RESTRICT"),
        nullable=False,
    )
    financial_case_event_id = db.Column(
        db.String(36),
        db.ForeignKey("financial_case_events.id", name="fk_financial_case_lot_evaluations_event", ondelete="RESTRICT"),
        nullable=False,
    )
    financial_line_id = db.Column(
        db.String(36),
        db.ForeignKey("financial_lines.id", name="fk_financial_case_lot_evaluations_line", ondelete="RESTRICT"),
        nullable=False,
    )
    lot_id = db.Column(
        db.String(36),
        db.ForeignKey("credit_lots.id", name="fk_financial_case_lot_evaluations_lot", ondelete="RESTRICT"),
        nullable=False,
    )
    funding_kind = db.Column(db.String(32), nullable=False)
    funding_reference_id = db.Column(db.String(36), nullable=False)
    case_type = db.Column(db.String(16), nullable=False)
    case_state = db.Column(db.String(32), nullable=False)
    line_principal_minor = db.Column(db.BigInteger, nullable=False)
    attributed_principal_minor = db.Column(db.BigInteger, nullable=False)
    unused_basis = db.Column(db.BigInteger, nullable=False)
    target_amount = db.Column(db.BigInteger, nullable=False)
    held_before = db.Column(db.BigInteger, nullable=False)
    reversed_before = db.Column(db.BigInteger, nullable=False)
    hold_amount = db.Column(db.BigInteger, nullable=False)
    release_amount = db.Column(db.BigInteger, nullable=False)
    reversal_amount = db.Column(db.BigInteger, nullable=False)
    recovery_amount = db.Column(db.BigInteger, nullable=False)
    unrestorable_recovery_amount = db.Column(db.BigInteger, nullable=False)
    absorbed_shortfall_total = db.Column(db.BigInteger, nullable=False)
    evaluation_key = db.Column(db.String(512), nullable=False)
    request_fingerprint = db.Column(db.String(64), nullable=False)
    idempotency_registry_id = db.Column(
        db.String(36),
        db.ForeignKey("idempotency_registry.id", name="fk_financial_case_lot_evaluations_registry", ondelete="RESTRICT"),
        nullable=False,
    )
    contract_version = db.Column(db.Integer, nullable=False)
    evaluated_at = db.Column(db.DateTime(timezone=True), nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    __table_args__ = (
        db.CheckConstraint(
            f"funding_kind IN ({_quoted(FUNDING_KINDS)})",
            name="ck_financial_case_lot_evaluations_funding_kind",
        ),
        db.CheckConstraint(
            "case_type IN ('refund', 'dispute')",
            name="ck_financial_case_lot_evaluations_case_type",
        ),
        db.CheckConstraint(
            "line_principal_minor > 0 AND attributed_principal_minor >= 0 "
            "AND attributed_principal_minor <= line_principal_minor "
            "AND unused_basis >= 0 AND target_amount >= 0 AND target_amount <= unused_basis "
            "AND held_before >= 0 AND reversed_before >= 0 AND hold_amount >= 0 "
            "AND release_amount >= 0 AND reversal_amount >= 0 AND recovery_amount >= 0 "
            "AND unrestorable_recovery_amount >= 0 AND absorbed_shortfall_total >= 0 "
            "AND recovery_amount + unrestorable_recovery_amount <= reversed_before",
            name="ck_financial_case_lot_evaluations_amounts",
        ),
        db.CheckConstraint(
            "(case_type = 'refund' AND hold_amount = 0 AND release_amount = 0 "
            "AND absorbed_shortfall_total = 0) OR case_type = 'dispute'",
            name="ck_financial_case_lot_evaluations_shape",
        ),
        db.CheckConstraint(
            "contract_version = 1 AND length(trim(evaluation_key)) > 0 "
            "AND length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint) "
            "AND evaluation_key = 'financial-case-evaluation:' || financial_case_event_id || ':' || lot_id",
            name="ck_financial_case_lot_evaluations_identity",
        ),
        db.UniqueConstraint(
            "financial_case_event_id", "lot_id",
            name="uq_financial_case_lot_evaluations_event_lot",
        ),
        db.UniqueConstraint("evaluation_key", name="uq_financial_case_lot_evaluations_key"),
        db.UniqueConstraint("idempotency_registry_id", name="uq_financial_case_lot_evaluations_registry"),
        db.Index("ix_financial_case_lot_evaluations_case_lot", "financial_case_id", "lot_id", "created_at"),
        db.Index("ix_financial_case_lot_evaluations_line", "financial_line_id"),
    )


class FinancialCaseCreditEffect(db.Model):
    """Immutable provenance for one Phase 3 entry created by a case evaluation."""

    __tablename__ = "financial_case_credit_effects"

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    evaluation_id = db.Column(
        db.String(36),
        db.ForeignKey("financial_case_lot_evaluations.id", name="fk_financial_case_credit_effects_evaluation", ondelete="RESTRICT"),
        nullable=False,
    )
    billing_account_id = db.Column(
        db.String(36),
        db.ForeignKey("billing_accounts.id", name="fk_financial_case_credit_effects_account", ondelete="RESTRICT"),
        nullable=False,
    )
    financial_case_id = db.Column(
        db.String(36),
        db.ForeignKey("financial_cases.id", name="fk_financial_case_credit_effects_case", ondelete="RESTRICT"),
        nullable=False,
    )
    lot_id = db.Column(
        db.String(36),
        db.ForeignKey("credit_lots.id", name="fk_financial_case_credit_effects_lot", ondelete="RESTRICT"),
        nullable=False,
    )
    credit_ledger_entry_id = db.Column(
        db.String(36),
        db.ForeignKey("credit_ledger_entries.id", name="fk_financial_case_credit_effects_entry", ondelete="RESTRICT"),
        nullable=False,
    )
    effect_type = db.Column(db.String(16), nullable=False)
    amount = db.Column(db.BigInteger, nullable=False)
    created_at = db.Column(db.DateTime(timezone=True), nullable=False, server_default=db.func.now())

    __table_args__ = (
        db.CheckConstraint(
            f"effect_type IN ({_quoted(CREDIT_EFFECT_TYPES)})",
            name="ck_financial_case_credit_effects_type",
        ),
        db.CheckConstraint("amount > 0", name="ck_financial_case_credit_effects_amount"),
        db.UniqueConstraint("credit_ledger_entry_id", name="uq_financial_case_credit_effects_entry"),
        db.Index("ix_financial_case_credit_effects_case_lot", "financial_case_id", "lot_id", "effect_type"),
        db.Index("ix_financial_case_credit_effects_evaluation", "evaluation_id"),
    )
