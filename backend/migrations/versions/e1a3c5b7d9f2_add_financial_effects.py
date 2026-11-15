"""Add inactive Phase 9 purchase funding and financial-case credit-effect evidence.

Revision ID: e1a3c5b7d9f2
Revises: b8c2d4e6f8a1
"""

from alembic import op
import sqlalchemy as sa


revision = "e1a3c5b7d9f2"
down_revision = "b8c2d4e6f8a1"
branch_labels = None
depends_on = None


TABLES = (
    "financial_case_credit_effects", "financial_case_lot_evaluations", "credit_purchase_fundings",
)
CASE_LEDGER_TYPES = "'dispute_hold','refund_reversal','dispute_reversal','recovery'"


class Phase9EvidenceNotEmptyError(RuntimeError):
    pass


def _create_tables():
    op.create_table(
        "credit_purchase_fundings",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("financial_transaction_id", sa.String(36), nullable=False),
        sa.Column("financial_line_id", sa.String(36), nullable=False),
        sa.Column("entitlement_definition_id", sa.String(36), nullable=False),
        sa.Column("package_component", sa.String(64), nullable=False),
        sa.Column("funding_key", sa.String(512), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("credit_amount", sa.BigInteger(), nullable=False),
        sa.Column("paid_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lot_id", sa.String(36), nullable=False),
        sa.Column("grant_entry_id", sa.String(36), nullable=False),
        sa.Column("idempotency_registry_id", sa.String(36), nullable=False),
        sa.Column("domain_event_id", sa.String(36), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("actor_type", sa.String(40), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("credit_amount > 0", name="ck_credit_purchase_fundings_amount"),
        sa.CheckConstraint("contract_version = 1", name="ck_credit_purchase_fundings_contract"),
        sa.CheckConstraint(
            "length(trim(package_component)) > 0 AND length(trim(funding_key)) > 0 "
            "AND length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint) "
            "AND funding_key = 'purchase:' || financial_line_id || ':' || package_component "
            "AND length(trim(actor_type)) > 0 AND length(trim(actor_id)) > 0",
            name="ck_credit_purchase_fundings_identity",
        ),
        sa.ForeignKeyConstraint(["billing_account_id"], ["billing_accounts.id"], name="fk_credit_purchase_fundings_account", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["financial_transaction_id"], ["financial_transactions.id"], name="fk_credit_purchase_fundings_transaction", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["financial_line_id"], ["financial_lines.id"], name="fk_credit_purchase_fundings_line", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["entitlement_definition_id"], ["entitlement_definitions.id"], name="fk_credit_purchase_fundings_definition", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lot_id"], ["credit_lots.id"], name="fk_credit_purchase_fundings_lot", ondelete="RESTRICT", deferrable=True, initially="DEFERRED"),
        sa.ForeignKeyConstraint(["grant_entry_id"], ["credit_ledger_entries.id"], name="fk_credit_purchase_fundings_grant", ondelete="RESTRICT", deferrable=True, initially="DEFERRED"),
        sa.ForeignKeyConstraint(["idempotency_registry_id"], ["idempotency_registry.id"], name="fk_credit_purchase_fundings_registry", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["domain_event_id"], ["domain_events.id"], name="fk_credit_purchase_fundings_domain_event", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_credit_purchase_fundings"),
        sa.UniqueConstraint("funding_key", name="uq_credit_purchase_fundings_key"),
        sa.UniqueConstraint("financial_line_id", "package_component", name="uq_credit_purchase_fundings_line_component"),
        sa.UniqueConstraint("lot_id", name="uq_credit_purchase_fundings_lot"),
        sa.UniqueConstraint("grant_entry_id", name="uq_credit_purchase_fundings_grant"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_credit_purchase_fundings_registry"),
    )
    op.create_index("ix_credit_purchase_fundings_account_paid", "credit_purchase_fundings", ["billing_account_id", "paid_at", "id"])
    op.create_index("ix_credit_purchase_fundings_domain_event", "credit_purchase_fundings", ["domain_event_id"])

    op.create_table(
        "financial_case_lot_evaluations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("financial_case_id", sa.String(36), nullable=False),
        sa.Column("financial_case_event_id", sa.String(36), nullable=False),
        sa.Column("financial_line_id", sa.String(36), nullable=False),
        sa.Column("lot_id", sa.String(36), nullable=False),
        sa.Column("funding_kind", sa.String(32), nullable=False),
        sa.Column("funding_reference_id", sa.String(36), nullable=False),
        sa.Column("case_type", sa.String(16), nullable=False),
        sa.Column("case_state", sa.String(32), nullable=False),
        *(sa.Column(name, sa.BigInteger(), nullable=False) for name in (
            "line_principal_minor", "attributed_principal_minor", "unused_basis", "target_amount",
            "held_before", "reversed_before", "hold_amount", "release_amount", "reversal_amount",
            "recovery_amount", "unrestorable_recovery_amount", "absorbed_shortfall_total",
        )),
        sa.Column("evaluation_key", sa.String(512), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("idempotency_registry_id", sa.String(36), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "funding_kind IN ('credit_purchase', 'recurring_allocation', 'upgrade_allocation')",
            name="ck_financial_case_lot_evaluations_funding_kind",
        ),
        sa.CheckConstraint("case_type IN ('refund', 'dispute')", name="ck_financial_case_lot_evaluations_case_type"),
        sa.CheckConstraint(
            "line_principal_minor > 0 AND attributed_principal_minor >= 0 "
            "AND attributed_principal_minor <= line_principal_minor "
            "AND unused_basis >= 0 AND target_amount >= 0 AND target_amount <= unused_basis "
            "AND held_before >= 0 AND reversed_before >= 0 AND hold_amount >= 0 "
            "AND release_amount >= 0 AND reversal_amount >= 0 AND recovery_amount >= 0 "
            "AND unrestorable_recovery_amount >= 0 AND absorbed_shortfall_total >= 0 "
            "AND recovery_amount + unrestorable_recovery_amount <= reversed_before",
            name="ck_financial_case_lot_evaluations_amounts",
        ),
        sa.CheckConstraint(
            "(case_type = 'refund' AND hold_amount = 0 AND release_amount = 0 "
            "AND absorbed_shortfall_total = 0) OR case_type = 'dispute'",
            name="ck_financial_case_lot_evaluations_shape",
        ),
        sa.CheckConstraint(
            "contract_version = 1 AND length(trim(evaluation_key)) > 0 "
            "AND length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint) "
            "AND evaluation_key = 'financial-case-evaluation:' || financial_case_event_id || ':' || lot_id",
            name="ck_financial_case_lot_evaluations_identity",
        ),
        sa.ForeignKeyConstraint(["billing_account_id"], ["billing_accounts.id"], name="fk_financial_case_lot_evaluations_account", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["financial_case_id"], ["financial_cases.id"], name="fk_financial_case_lot_evaluations_case", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["financial_case_event_id"], ["financial_case_events.id"], name="fk_financial_case_lot_evaluations_event", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["financial_line_id"], ["financial_lines.id"], name="fk_financial_case_lot_evaluations_line", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lot_id"], ["credit_lots.id"], name="fk_financial_case_lot_evaluations_lot", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["idempotency_registry_id"], ["idempotency_registry.id"], name="fk_financial_case_lot_evaluations_registry", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_financial_case_lot_evaluations"),
        sa.UniqueConstraint("financial_case_event_id", "lot_id", name="uq_financial_case_lot_evaluations_event_lot"),
        sa.UniqueConstraint("evaluation_key", name="uq_financial_case_lot_evaluations_key"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_financial_case_lot_evaluations_registry"),
    )
    op.create_index("ix_financial_case_lot_evaluations_case_lot", "financial_case_lot_evaluations", ["financial_case_id", "lot_id", "created_at"])
    op.create_index("ix_financial_case_lot_evaluations_line", "financial_case_lot_evaluations", ["financial_line_id"])

    op.create_table(
        "financial_case_credit_effects",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("evaluation_id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("financial_case_id", sa.String(36), nullable=False),
        sa.Column("lot_id", sa.String(36), nullable=False),
        sa.Column("credit_ledger_entry_id", sa.String(36), nullable=False),
        sa.Column("effect_type", sa.String(16), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "effect_type IN ('hold', 'release', 'reversal', 'recovery')",
            name="ck_financial_case_credit_effects_type",
        ),
        sa.CheckConstraint("amount > 0", name="ck_financial_case_credit_effects_amount"),
        sa.ForeignKeyConstraint(["evaluation_id"], ["financial_case_lot_evaluations.id"], name="fk_financial_case_credit_effects_evaluation", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["billing_account_id"], ["billing_accounts.id"], name="fk_financial_case_credit_effects_account", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["financial_case_id"], ["financial_cases.id"], name="fk_financial_case_credit_effects_case", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lot_id"], ["credit_lots.id"], name="fk_financial_case_credit_effects_lot", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["credit_ledger_entry_id"], ["credit_ledger_entries.id"], name="fk_financial_case_credit_effects_entry", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_financial_case_credit_effects"),
        sa.UniqueConstraint("credit_ledger_entry_id", name="uq_financial_case_credit_effects_entry"),
    )
    op.create_index("ix_financial_case_credit_effects_case_lot", "financial_case_credit_effects", ["financial_case_id", "lot_id", "effect_type"])
    op.create_index("ix_financial_case_credit_effects_evaluation", "financial_case_credit_effects", ["evaluation_id"])


def _postgresql_guards():
    op.execute("""
    CREATE FUNCTION phase9_funding_ok(p_kind text, p_ref text, p_line text, p_lot text) RETURNS boolean AS $$
      SELECT CASE p_kind
        WHEN 'credit_purchase' THEN EXISTS (
          SELECT 1 FROM credit_purchase_fundings f
          WHERE f.id=p_ref AND f.financial_line_id=p_line AND f.lot_id=p_lot)
        WHEN 'recurring_allocation' THEN EXISTS (
          SELECT 1 FROM recurring_credit_allocations a JOIN credit_periods p ON p.id=a.credit_period_id
          WHERE a.id=p_ref AND a.financial_line_id=p_line AND p.funded_lot_id=p_lot)
        WHEN 'upgrade_allocation' THEN EXISTS (
          SELECT 1 FROM upgrade_credit_allocations u
          WHERE u.id=p_ref AND u.financial_line_id=p_line AND u.funded_lot_id=p_lot)
        ELSE false END
    $$ LANGUAGE sql STABLE;

    CREATE FUNCTION phase9_reject_row_change() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Phase 9 financial-effect evidence is immutable'; END;
    $$ LANGUAGE plpgsql;

    CREATE FUNCTION phase9_reject_truncate() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Phase 9 financial-effect evidence cannot be truncated'; END;
    $$ LANGUAGE plpgsql;

    CREATE FUNCTION phase9_purchase_funding_guard() RETURNS trigger AS $$
    DECLARE tx financial_transactions%ROWTYPE; line financial_lines%ROWTYPE;
            account billing_accounts%ROWTYPE; definition entitlement_definitions%ROWTYPE;
            terms jsonb;
    BEGIN
      SELECT * INTO line FROM financial_lines WHERE id=NEW.financial_line_id;
      SELECT * INTO tx FROM financial_transactions WHERE id=NEW.financial_transaction_id;
      SELECT * INTO account FROM billing_accounts WHERE id=NEW.billing_account_id;
      SELECT * INTO definition FROM entitlement_definitions WHERE id=NEW.entitlement_definition_id;
      terms := definition.funding_policy_json::jsonb -> 'purchase';
      IF line.id IS NULL OR tx.id IS NULL OR account.id IS NULL OR definition.id IS NULL
         OR line.financial_transaction_id<>tx.id OR tx.billing_account_id<>account.id
         OR tx.kind<>'payment' OR tx.principal_minor<=0 OR tx.currency<>account.currency
         OR line.line_kind<>'credit_pack' OR line.subscription_id IS NOT NULL
         OR line.entitlement_instance_id IS NOT NULL OR line.currency<>account.currency
         OR line.principal_minor<=0 OR line.discount_minor>0
         OR line.principal_minor+line.discount_minor<=0
         OR NEW.paid_at<>tx.effective_at THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='purchase funding requires a successful credit-pack payment line for this account';
      END IF;
      IF definition.approved_at IS NULL OR definition.effective_at IS NULL
         OR definition.effective_at>tx.effective_at
         OR (definition.retired_at IS NOT NULL AND definition.retired_at<=tx.effective_at)
         OR terms IS NULL OR terms->>'line_kind' IS DISTINCT FROM 'credit_pack'
         OR terms->>'source_type' IS DISTINCT FROM line.source_type
         OR terms->>'source_id' IS DISTINCT FROM line.source_id
         OR terms->>'currency' IS DISTINCT FROM line.currency
         OR (terms->>'quantity')::bigint IS DISTINCT FROM line.quantity
         OR (terms->>'unit_principal_minor')::bigint * line.quantity IS DISTINCT FROM line.principal_minor
         OR terms->'expiry' IS DISTINCT FROM '{"kind":"none"}'::jsonb
         OR NOT EXISTS (
           SELECT 1 FROM jsonb_array_elements(terms->'components') component
           WHERE component->>'component'=NEW.package_component
             AND (component->>'credit_amount')::bigint=NEW.credit_amount) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='purchase funding must match its approved purchase definition';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM idempotency_registry r WHERE r.id=NEW.idempotency_registry_id
                       AND r.namespace='credit_purchase_funding' AND r.key=NEW.funding_key)
         OR NOT EXISTS (SELECT 1 FROM domain_events e WHERE e.id=NEW.domain_event_id
                          AND e.billing_account_id=NEW.billing_account_id
                          AND e.event_type='credit_purchase_funded'
                          AND e.event_key='credit_purchase_funded:' || NEW.financial_line_id
                          AND EXISTS (SELECT 1 FROM communication_outbox o WHERE o.domain_event_id=e.id)) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='purchase funding requires its claim and communication evidence';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase9_purchase_funding_guard BEFORE INSERT ON credit_purchase_fundings
      FOR EACH ROW EXECUTE FUNCTION phase9_purchase_funding_guard();
    CREATE TRIGGER trg_phase9_purchase_funding_immutable BEFORE UPDATE OR DELETE ON credit_purchase_fundings
      FOR EACH ROW EXECUTE FUNCTION phase9_reject_row_change();

    CREATE FUNCTION phase9_purchase_lot_guard() RETURNS trigger AS $$
    BEGIN
      IF NEW.source_type<>'credit_pack_purchase' THEN RETURN NEW; END IF;
      IF NOT EXISTS (SELECT 1 FROM credit_purchase_fundings f
                     WHERE f.id=NEW.source_id AND f.lot_id=NEW.id
                       AND f.billing_account_id=NEW.billing_account_id
                       AND f.credit_amount=NEW.original_amount
                       AND f.paid_at=NEW.available_at AND NEW.expires_at IS NULL) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='purchased credit lot requires Phase 9 purchase funding evidence';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase9_purchase_lot_guard BEFORE INSERT ON credit_lots
      FOR EACH ROW EXECUTE FUNCTION phase9_purchase_lot_guard();

    CREATE FUNCTION phase9_purchase_grant_guard() RETURNS trigger AS $$
    DECLARE lot_row credit_lots%ROWTYPE;
    BEGIN
      IF NEW.entry_type<>'grant' THEN RETURN NEW; END IF;
      SELECT * INTO lot_row FROM credit_lots WHERE id=NEW.lot_id;
      IF lot_row.source_type<>'credit_pack_purchase' THEN RETURN NEW; END IF;
      IF NOT EXISTS (SELECT 1 FROM credit_purchase_fundings f
                     WHERE f.lot_id=NEW.lot_id AND f.grant_entry_id=NEW.id
                       AND f.idempotency_registry_id=NEW.idempotency_registry_id
                       AND f.credit_amount=NEW.available_delta) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='purchased credit grant requires Phase 9 purchase funding evidence';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase9_purchase_grant_guard BEFORE INSERT ON credit_ledger_entries
      FOR EACH ROW EXECUTE FUNCTION phase9_purchase_grant_guard();

    CREATE FUNCTION phase9_evaluation_guard() RETURNS trigger AS $$
    DECLARE case_row financial_cases%ROWTYPE; event_row financial_case_events%ROWTYPE;
            line financial_lines%ROWTYPE; lot_row credit_lots%ROWTYPE;
    BEGIN
      SELECT * INTO case_row FROM financial_cases WHERE id=NEW.financial_case_id;
      SELECT * INTO event_row FROM financial_case_events WHERE id=NEW.financial_case_event_id;
      SELECT * INTO line FROM financial_lines WHERE id=NEW.financial_line_id;
      SELECT * INTO lot_row FROM credit_lots WHERE id=NEW.lot_id;
      IF case_row.id IS NULL OR event_row.id IS NULL OR line.id IS NULL OR lot_row.id IS NULL
         OR event_row.financial_case_id<>case_row.id
         OR case_row.current_event_id<>event_row.id
         OR case_row.billing_account_id<>NEW.billing_account_id
         OR lot_row.billing_account_id<>NEW.billing_account_id
         OR case_row.case_type<>NEW.case_type OR case_row.state<>NEW.case_state
         OR line.financial_transaction_id<>case_row.source_financial_transaction_id
         OR line.principal_minor+line.discount_minor<>NEW.line_principal_minor
         OR NOT phase9_funding_ok(NEW.funding_kind, NEW.funding_reference_id, line.id, lot_row.id) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='case evaluation must bind the current case version to a lot funded by its source line';
      END IF;
      IF NEW.attributed_principal_minor<>COALESCE((
           SELECT attributed_principal_minor FROM financial_case_event_lines
           WHERE financial_case_event_id=event_row.id AND financial_line_id=line.id), 0) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='case evaluation principal must equal the accepted line attribution';
      END IF;
      IF NOT EXISTS (SELECT 1 FROM idempotency_registry r WHERE r.id=NEW.idempotency_registry_id
                       AND r.namespace='financial_case_evaluation' AND r.key=NEW.evaluation_key) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='case evaluation requires its claim';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase9_evaluation_guard BEFORE INSERT ON financial_case_lot_evaluations
      FOR EACH ROW EXECUTE FUNCTION phase9_evaluation_guard();
    CREATE TRIGGER trg_phase9_evaluation_immutable BEFORE UPDATE OR DELETE ON financial_case_lot_evaluations
      FOR EACH ROW EXECUTE FUNCTION phase9_reject_row_change();

    CREATE FUNCTION phase9_effect_guard() RETURNS trigger AS $$
    DECLARE ev financial_case_lot_evaluations%ROWTYPE; entry credit_ledger_entries%ROWTYPE;
            related credit_ledger_entries%ROWTYPE; ok boolean; recovered bigint; reversed bigint;
    BEGIN
      SELECT * INTO ev FROM financial_case_lot_evaluations WHERE id=NEW.evaluation_id;
      SELECT * INTO entry FROM credit_ledger_entries WHERE id=NEW.credit_ledger_entry_id;
      SELECT * INTO related FROM credit_ledger_entries WHERE id=entry.related_entry_id;
      IF ev.id IS NULL OR entry.id IS NULL
         OR ev.billing_account_id<>NEW.billing_account_id OR ev.financial_case_id<>NEW.financial_case_id
         OR ev.lot_id<>NEW.lot_id OR entry.lot_id<>NEW.lot_id
         OR entry.billing_account_id<>NEW.billing_account_id THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='credit effect must belong to its evaluation lot and account';
      END IF;
      ok := CASE NEW.effect_type
        WHEN 'hold' THEN ev.case_type='dispute' AND entry.entry_type='dispute_hold'
             AND entry.held_delta=NEW.amount
        WHEN 'release' THEN ev.case_type='dispute' AND entry.entry_type='release'
             AND entry.reservation_id IS NULL AND -entry.held_delta=NEW.amount
             AND EXISTS (SELECT 1 FROM financial_case_credit_effects x
                         WHERE x.credit_ledger_entry_id=entry.related_entry_id
                           AND x.financial_case_id=NEW.financial_case_id AND x.effect_type='hold')
        WHEN 'reversal' THEN (
             ev.case_type='refund' AND entry.entry_type='refund_reversal'
             AND -entry.available_delta=NEW.amount AND related.entry_type IN ('grant','migration_opening'))
          OR (ev.case_type='dispute' AND entry.entry_type='dispute_reversal'
             AND -entry.held_delta=NEW.amount
             AND EXISTS (SELECT 1 FROM financial_case_credit_effects x
                         WHERE x.credit_ledger_entry_id=entry.related_entry_id
                           AND x.financial_case_id=NEW.financial_case_id AND x.effect_type='hold'))
        WHEN 'recovery' THEN entry.entry_type='recovery' AND entry.available_delta=NEW.amount
             AND EXISTS (SELECT 1 FROM financial_case_credit_effects x
                         WHERE x.credit_ledger_entry_id=entry.related_entry_id
                           AND x.financial_case_id=NEW.financial_case_id AND x.effect_type='reversal')
        ELSE false END;
      IF NOT COALESCE(ok, false) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='credit effect does not match its ledger entry and case provenance';
      END IF;
      IF NEW.effect_type='recovery' THEN
        SELECT COALESCE(sum(amount),0) INTO recovered FROM financial_case_credit_effects
          WHERE financial_case_id=NEW.financial_case_id AND lot_id=NEW.lot_id AND effect_type='recovery';
        SELECT COALESCE(sum(amount),0) INTO reversed FROM financial_case_credit_effects
          WHERE financial_case_id=NEW.financial_case_id AND lot_id=NEW.lot_id AND effect_type='reversal';
        IF recovered + NEW.amount > reversed THEN
          RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='recovery cannot exceed value previously reversed for this source';
        END IF;
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase9_effect_guard BEFORE INSERT ON financial_case_credit_effects
      FOR EACH ROW EXECUTE FUNCTION phase9_effect_guard();
    CREATE TRIGGER trg_phase9_effect_immutable BEFORE UPDATE OR DELETE ON financial_case_credit_effects
      FOR EACH ROW EXECUTE FUNCTION phase9_reject_row_change();

    CREATE FUNCTION phase9_case_entry_final() RETURNS trigger AS $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM financial_case_credit_effects effect
        JOIN financial_case_lot_evaluations ev ON ev.id=effect.evaluation_id
        JOIN financial_case_event_ledger_entries link
          ON link.credit_ledger_entry_id=effect.credit_ledger_entry_id
         AND link.financial_case_event_id=ev.financial_case_event_id
         AND link.effect_type=effect.effect_type
        WHERE effect.credit_ledger_entry_id=NEW.id) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='refund, dispute, and recovery ledger entries require Phase 9 case provenance';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    CREATE CONSTRAINT TRIGGER trg_phase9_case_entry_final AFTER INSERT ON credit_ledger_entries
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW
      WHEN (NEW.entry_type IN (""" + CASE_LEDGER_TYPES + """)
            OR (NEW.entry_type='release' AND NEW.reservation_id IS NULL))
      EXECUTE FUNCTION phase9_case_entry_final();

    CREATE TRIGGER trg_phase9_purchase_funding_no_truncate BEFORE TRUNCATE ON credit_purchase_fundings
      FOR EACH STATEMENT EXECUTE FUNCTION phase9_reject_truncate();
    CREATE TRIGGER trg_phase9_evaluation_no_truncate BEFORE TRUNCATE ON financial_case_lot_evaluations
      FOR EACH STATEMENT EXECUTE FUNCTION phase9_reject_truncate();
    CREATE TRIGGER trg_phase9_effect_no_truncate BEFORE TRUNCATE ON financial_case_credit_effects
      FOR EACH STATEMENT EXECUTE FUNCTION phase9_reject_truncate();
    """)


PG_TRIGGERS = (
    ("trg_phase9_effect_no_truncate", "financial_case_credit_effects"),
    ("trg_phase9_evaluation_no_truncate", "financial_case_lot_evaluations"),
    ("trg_phase9_purchase_funding_no_truncate", "credit_purchase_fundings"),
    ("trg_phase9_case_entry_final", "credit_ledger_entries"),
    ("trg_phase9_effect_immutable", "financial_case_credit_effects"),
    ("trg_phase9_effect_guard", "financial_case_credit_effects"),
    ("trg_phase9_evaluation_immutable", "financial_case_lot_evaluations"),
    ("trg_phase9_evaluation_guard", "financial_case_lot_evaluations"),
    ("trg_phase9_purchase_grant_guard", "credit_ledger_entries"),
    ("trg_phase9_purchase_lot_guard", "credit_lots"),
    ("trg_phase9_purchase_funding_immutable", "credit_purchase_fundings"),
    ("trg_phase9_purchase_funding_guard", "credit_purchase_fundings"),
)
PG_FUNCTIONS = (
    "phase9_case_entry_final()", "phase9_effect_guard()", "phase9_evaluation_guard()",
    "phase9_purchase_grant_guard()", "phase9_purchase_lot_guard()",
    "phase9_purchase_funding_guard()", "phase9_reject_truncate()", "phase9_reject_row_change()",
    "phase9_funding_ok(text, text, text, text)",
)
SQLITE_TRIGGERS = (
    "trg_phase9_credit_purchase_fundings_update", "trg_phase9_credit_purchase_fundings_delete",
    "trg_phase9_financial_case_lot_evaluations_update", "trg_phase9_financial_case_lot_evaluations_delete",
    "trg_phase9_financial_case_credit_effects_update", "trg_phase9_financial_case_credit_effects_delete",
    "trg_phase9_purchase_lot_insert", "trg_phase9_effect_insert",
)


def _sqlite_guards():
    for table in TABLES:
        for action in ("update", "delete"):
            op.execute(
                f"CREATE TRIGGER trg_phase9_{table}_{action} BEFORE {action.upper()} ON {table} "
                "BEGIN SELECT RAISE(ABORT,'Phase 9 financial-effect evidence is immutable'); END"
            )
    op.execute(
        "CREATE TRIGGER trg_phase9_purchase_lot_insert BEFORE INSERT ON credit_lots "
        "WHEN NEW.source_type='credit_pack_purchase' AND NOT EXISTS ("
        "SELECT 1 FROM credit_purchase_fundings f WHERE f.id=NEW.source_id AND f.lot_id=NEW.id "
        "AND f.billing_account_id=NEW.billing_account_id AND f.credit_amount=NEW.original_amount "
        "AND NEW.expires_at IS NULL) "
        "BEGIN SELECT RAISE(ABORT,'purchased credit lot requires Phase 9 purchase funding evidence'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_phase9_effect_insert BEFORE INSERT ON financial_case_credit_effects BEGIN "
        "SELECT RAISE(ABORT,'credit effect must belong to its evaluation lot and account') "
        "WHERE NOT EXISTS (SELECT 1 FROM financial_case_lot_evaluations ev "
        "JOIN credit_ledger_entries e ON e.id=NEW.credit_ledger_entry_id "
        "WHERE ev.id=NEW.evaluation_id AND ev.lot_id=NEW.lot_id AND e.lot_id=NEW.lot_id "
        "AND ev.financial_case_id=NEW.financial_case_id "
        "AND ev.billing_account_id=NEW.billing_account_id AND e.billing_account_id=NEW.billing_account_id); "
        "SELECT RAISE(ABORT,'recovery cannot exceed value previously reversed for this source') "
        "WHERE NEW.effect_type='recovery' AND "
        "(SELECT COALESCE(sum(amount),0) FROM financial_case_credit_effects "
        " WHERE financial_case_id=NEW.financial_case_id AND lot_id=NEW.lot_id AND effect_type='recovery') "
        "+ NEW.amount > "
        "(SELECT COALESCE(sum(amount),0) FROM financial_case_credit_effects "
        " WHERE financial_case_id=NEW.financial_case_id AND lot_id=NEW.lot_id AND effect_type='reversal'); "
        "END"
    )


def upgrade():
    _create_tables()
    if op.get_bind().dialect.name == "postgresql":
        _postgresql_guards()
    else:
        _sqlite_guards()


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in TABLES:
            op.execute(sa.text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE"))
    for table in TABLES:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None:
            raise Phase9EvidenceNotEmptyError("Phase 9 downgrade refuses to discard financial-effect evidence")
    if bind.dialect.name == "postgresql":
        for trigger, table in PG_TRIGGERS:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))
        for function in PG_FUNCTIONS:
            op.execute(sa.text(f"DROP FUNCTION IF EXISTS {function}"))
    else:
        for trigger in SQLITE_TRIGGERS:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))
    op.drop_index("ix_financial_case_credit_effects_evaluation", table_name="financial_case_credit_effects")
    op.drop_index("ix_financial_case_credit_effects_case_lot", table_name="financial_case_credit_effects")
    op.drop_index("ix_financial_case_lot_evaluations_line", table_name="financial_case_lot_evaluations")
    op.drop_index("ix_financial_case_lot_evaluations_case_lot", table_name="financial_case_lot_evaluations")
    op.drop_index("ix_credit_purchase_fundings_domain_event", table_name="credit_purchase_fundings")
    op.drop_index("ix_credit_purchase_fundings_account_paid", table_name="credit_purchase_fundings")
    for table in TABLES:
        op.drop_table(table)
