"""Add inactive Phase 8 seat commitments and seat-change history.

Revision ID: b8c2d4e6f8a1
Revises: a7d9e2f4b6c8
"""

from alembic import op
import sqlalchemy as sa


revision = "b8c2d4e6f8a1"
down_revision = "a7d9e2f4b6c8"
branch_labels = None
depends_on = None


TABLES = (
    "seat_change_events", "seat_funding_uses", "seat_term_fundings", "seat_funding_attributions",
    "seat_changes", "seat_commitments", "seat_commitment_fences",
)
CHANGE_STATES = (
    "'increased','scheduled_reduction','blocked_occupancy','awaiting_payment',"
    "'reduced','cancelled','superseded'"
)
ACTIVE_STATES = "'scheduled_reduction','blocked_occupancy','awaiting_payment'"
# Paid occupancy mirrors app.orgs.normalize_org_role over ORG_EDIT_ROLES,
# including the legacy aliases member/teammate (collaborator) and editor
# (creator). A test asserts this list matches the Python definition.
PAID_ROLE_SQL = "'owner','admin','creator','collaborator','member','teammate','editor'"


class Phase8EvidenceNotEmptyError(RuntimeError):
    pass


def _create_tables():
    op.create_table(
        "seat_commitment_fences",
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("fence_bit", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.ForeignKeyConstraint(["subscription_id"], ["billing_subscriptions.id"], name="fk_seat_commitment_fences_subscription", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("subscription_id", name="pk_seat_commitment_fences"),
    )
    op.create_table(
        "seat_commitments",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("origin_type", sa.String(24), nullable=False),
        sa.Column("state", sa.String(16), nullable=False, server_default="active"),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("previous_commitment_id", sa.String(36), nullable=True),
        sa.Column("idempotency_registry_id", sa.String(36), nullable=False),
        sa.Column("domain_event_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("quantity > 0", name="ck_seat_commitments_quantity"),
        sa.CheckConstraint("origin_type IN ('opening','increase','reduction')", name="ck_seat_commitments_origin"),
        sa.CheckConstraint(
            "(state='active' AND ends_at IS NULL) OR "
            "(state='replaced' AND ends_at IS NOT NULL AND ends_at >= starts_at)",
            name="ck_seat_commitments_interval",
        ),
        sa.CheckConstraint(
            "(origin_type='opening' AND previous_commitment_id IS NULL) OR "
            "(origin_type<>'opening' AND previous_commitment_id IS NOT NULL)",
            name="ck_seat_commitments_lineage",
        ),
        sa.CheckConstraint("previous_commitment_id IS NULL OR previous_commitment_id<>id", name="ck_seat_commitments_not_self"),
        sa.ForeignKeyConstraint(["billing_account_id"], ["billing_accounts.id"], name="fk_seat_commitments_account", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subscription_id"], ["billing_subscriptions.id"], name="fk_seat_commitments_subscription", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["previous_commitment_id"], ["seat_commitments.id"], name="fk_seat_commitments_previous", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["idempotency_registry_id"], ["idempotency_registry.id"], name="fk_seat_commitments_registry", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["domain_event_id"], ["domain_events.id"], name="fk_seat_commitments_domain_event", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_seat_commitments"),
        sa.UniqueConstraint("previous_commitment_id", name="uq_seat_commitments_previous"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_seat_commitments_registry"),
        sa.UniqueConstraint("domain_event_id", name="uq_seat_commitments_domain_event"),
    )
    op.create_table(
        "seat_changes",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("base_commitment_id", sa.String(36), nullable=False),
        sa.Column("result_commitment_id", sa.String(36), nullable=True),
        sa.Column("base_quantity", sa.Integer(), nullable=False),
        sa.Column("target_quantity", sa.Integer(), nullable=False),
        sa.Column("seat_delta", sa.Integer(), nullable=True),
        sa.Column("occupancy_at_request", sa.Integer(), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorizing_role_grant_id", sa.String(36), nullable=False),
        sa.Column("requested_by_user_id", sa.String(36), nullable=False),
        sa.Column("command_key", sa.String(512), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("idempotency_registry_id", sa.String(36), nullable=False),
        sa.Column("domain_event_id", sa.String(36), nullable=False),
        sa.Column("supersedes_change_id", sa.String(36), nullable=True),
        sa.Column("last_event_id", sa.String(36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('increase','reduction')", name="ck_seat_changes_kind"),
        sa.CheckConstraint(f"state IN ({CHANGE_STATES})", name="ck_seat_changes_state"),
        sa.CheckConstraint(
            "(kind='increase' AND state='increased' AND seat_delta IS NOT NULL AND seat_delta>0 "
            "AND target_quantity=base_quantity+seat_delta "
            "AND result_commitment_id IS NOT NULL AND requested_at<=effective_at) OR "
            "(kind='reduction' AND state<>'increased' AND seat_delta IS NULL "
            "AND target_quantity<base_quantity "
            "AND requested_at<effective_at "
            "AND ((state='reduced' AND result_commitment_id IS NOT NULL) OR "
            "(state<>'reduced' AND result_commitment_id IS NULL)))",
            name="ck_seat_changes_shape",
        ),
        sa.CheckConstraint("base_quantity>0 AND target_quantity>0 AND occupancy_at_request>=0", name="ck_seat_changes_quantities"),
        sa.CheckConstraint(
            "length(trim(command_key))>0 AND length(request_fingerprint)=64 "
            "AND request_fingerprint=lower(request_fingerprint)",
            name="ck_seat_changes_identity",
        ),
        sa.CheckConstraint("supersedes_change_id IS NULL OR supersedes_change_id<>id", name="ck_seat_changes_not_self"),
        sa.ForeignKeyConstraint(["billing_account_id"], ["billing_accounts.id"], name="fk_seat_changes_account", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subscription_id"], ["billing_subscriptions.id"], name="fk_seat_changes_subscription", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["base_commitment_id"], ["seat_commitments.id"], name="fk_seat_changes_base_commitment", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["result_commitment_id"], ["seat_commitments.id"], name="fk_seat_changes_result_commitment", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorizing_role_grant_id"], ["billing_role_grants.id"], name="fk_seat_changes_role_grant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], name="fk_seat_changes_requested_by", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["idempotency_registry_id"], ["idempotency_registry.id"], name="fk_seat_changes_registry", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["domain_event_id"], ["domain_events.id"], name="fk_seat_changes_domain_event", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supersedes_change_id"], ["seat_changes.id"], name="fk_seat_changes_supersedes", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_seat_changes"),
        sa.UniqueConstraint("command_key", name="uq_seat_changes_command_key"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_seat_changes_registry"),
        sa.UniqueConstraint("domain_event_id", name="uq_seat_changes_domain_event"),
        sa.UniqueConstraint("result_commitment_id", name="uq_seat_changes_result_commitment"),
    )
    op.create_table(
        "seat_funding_attributions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("financial_line_id", sa.String(36), nullable=False),
        sa.Column("seat_source", sa.String(16), nullable=False),
        sa.Column("seats", sa.Integer(), nullable=False),
        sa.Column("entitlement_definition_id", sa.String(36), nullable=True),
        sa.Column("term_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("term_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("evidence_reference", sa.String(255), nullable=False),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("idempotency_registry_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("seat_source IN ('included','purchased')", name="ck_seat_funding_attributions_source"),
        sa.CheckConstraint(
            "(seat_source='included' AND entitlement_definition_id IS NOT NULL AND seats>=0) OR "
            "(seat_source='purchased' AND entitlement_definition_id IS NULL AND seats>0)",
            name="ck_seat_funding_attributions_shape",
        ),
        sa.CheckConstraint("term_ends_at > term_starts_at", name="ck_seat_funding_attributions_term"),
        sa.CheckConstraint("contract_version = 1", name="ck_seat_funding_attributions_version"),
        sa.CheckConstraint(
            "length(trim(evidence_reference))>0 AND length(trim(actor_type))>0 AND length(trim(actor_id))>0",
            name="ck_seat_funding_attributions_text",
        ),
        sa.ForeignKeyConstraint(["billing_account_id"], ["billing_accounts.id"], name="fk_seat_funding_attributions_account", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subscription_id"], ["billing_subscriptions.id"], name="fk_seat_funding_attributions_subscription", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["financial_line_id"], ["financial_lines.id"], name="fk_seat_funding_attributions_line", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["entitlement_definition_id"], ["entitlement_definitions.id"], name="fk_seat_funding_attributions_definition", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["idempotency_registry_id"], ["idempotency_registry.id"], name="fk_seat_funding_attributions_registry", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_seat_funding_attributions"),
        sa.UniqueConstraint("financial_line_id", name="uq_seat_funding_attributions_line"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_seat_funding_attributions_registry"),
    )
    op.create_table(
        "seat_term_fundings",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("subscription_id", sa.String(36), nullable=False),
        sa.Column("commitment_id", sa.String(36), nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("term_starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("term_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("required_seats", sa.Integer(), nullable=False),
        sa.Column("funded_seats", sa.Integer(), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("supersedes_funding_id", sa.String(36), nullable=True),
        sa.Column("idempotency_registry_id", sa.String(36), nullable=False),
        sa.Column("domain_event_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("purpose IN ('opening','increase','renewal','top_up')", name="ck_seat_term_fundings_purpose"),
        sa.CheckConstraint("state IN ('funded','unresolved')", name="ck_seat_term_fundings_state"),
        sa.CheckConstraint(
            "required_seats>0 AND funded_seats>=0 AND funded_seats<=required_seats "
            "AND ((state='funded') = (funded_seats=required_seats)) AND term_ends_at>term_starts_at",
            name="ck_seat_term_fundings_amounts",
        ),
        sa.CheckConstraint(
            "(purpose IN ('opening','increase') AND state='funded' AND supersedes_funding_id IS NULL) OR "
            "(purpose='renewal' AND supersedes_funding_id IS NULL) OR "
            "(purpose='top_up' AND supersedes_funding_id IS NOT NULL)",
            name="ck_seat_term_fundings_shape",
        ),
        sa.CheckConstraint("supersedes_funding_id IS NULL OR supersedes_funding_id<>id", name="ck_seat_term_fundings_not_self"),
        sa.ForeignKeyConstraint(["billing_account_id"], ["billing_accounts.id"], name="fk_seat_term_fundings_account", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["subscription_id"], ["billing_subscriptions.id"], name="fk_seat_term_fundings_subscription", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["commitment_id"], ["seat_commitments.id"], name="fk_seat_term_fundings_commitment", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["supersedes_funding_id"], ["seat_term_fundings.id"], name="fk_seat_term_fundings_supersedes", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["idempotency_registry_id"], ["idempotency_registry.id"], name="fk_seat_term_fundings_registry", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["domain_event_id"], ["domain_events.id"], name="fk_seat_term_fundings_domain_event", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_seat_term_fundings"),
        sa.UniqueConstraint("supersedes_funding_id", name="uq_seat_term_fundings_supersedes"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_seat_term_fundings_registry"),
        sa.UniqueConstraint("domain_event_id", name="uq_seat_term_fundings_domain_event"),
    )
    op.create_table(
        "seat_funding_uses",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("attribution_id", sa.String(36), nullable=False),
        sa.Column("term_funding_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["attribution_id"], ["seat_funding_attributions.id"], name="fk_seat_funding_uses_attribution", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["term_funding_id"], ["seat_term_fundings.id"], name="fk_seat_funding_uses_term_funding", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_seat_funding_uses"),
        sa.UniqueConstraint("attribution_id", name="uq_seat_funding_uses_attribution"),
    )
    op.create_table(
        "seat_change_events",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("seat_change_id", sa.String(36), nullable=False),
        sa.Column("from_state", sa.String(32), nullable=False),
        sa.Column("to_state", sa.String(32), nullable=False),
        sa.Column("transition", sa.String(64), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("occupancy_observed", sa.Integer(), nullable=True),
        sa.Column("actor_type", sa.String(32), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        sa.Column("authorizing_role_grant_id", sa.String(36), nullable=True),
        sa.Column("term_funding_id", sa.String(36), nullable=True),
        sa.Column("result_commitment_id", sa.String(36), nullable=True),
        sa.Column("evidence_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_registry_id", sa.String(36), nullable=False),
        sa.Column("domain_event_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("from_state<>to_state", name="ck_seat_change_events_transition"),
        sa.CheckConstraint(
            "length(trim(transition))>0 AND length(trim(actor_type))>0 AND length(trim(actor_id))>0",
            name="ck_seat_change_events_text",
        ),
        sa.CheckConstraint(
            "(actor_type='user' AND authorizing_role_grant_id IS NOT NULL) OR "
            "(actor_type='system' AND authorizing_role_grant_id IS NULL)",
            name="ck_seat_change_events_actor",
        ),
        sa.CheckConstraint(
            "(to_state='reduced' AND result_commitment_id IS NOT NULL) OR "
            "(to_state<>'reduced' AND result_commitment_id IS NULL)",
            name="ck_seat_change_events_result",
        ),
        sa.CheckConstraint("occupancy_observed IS NULL OR occupancy_observed>=0", name="ck_seat_change_events_occupancy"),
        sa.CheckConstraint(
            "(to_state IN ('reduced','blocked_occupancy')) = (term_funding_id IS NOT NULL)",
            name="ck_seat_change_events_funding",
        ),
        sa.ForeignKeyConstraint(["seat_change_id"], ["seat_changes.id"], name="fk_seat_change_events_change", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["authorizing_role_grant_id"], ["billing_role_grants.id"], name="fk_seat_change_events_role_grant", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["term_funding_id"], ["seat_term_fundings.id"], name="fk_seat_change_events_term_funding", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["result_commitment_id"], ["seat_commitments.id"], name="fk_seat_change_events_result_commitment", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["idempotency_registry_id"], ["idempotency_registry.id"], name="fk_seat_change_events_registry", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["domain_event_id"], ["domain_events.id"], name="fk_seat_change_events_domain_event", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_seat_change_events"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_seat_change_events_registry"),
        sa.UniqueConstraint("domain_event_id", name="uq_seat_change_events_domain_event"),
        sa.UniqueConstraint("result_commitment_id", name="uq_seat_change_events_result_commitment"),
        sa.UniqueConstraint("term_funding_id", name="uq_seat_change_events_term_funding"),
    )
    op.create_index("ix_seat_commitments_subscription_starts", "seat_commitments", ["subscription_id", "starts_at", "id"])
    op.create_index(
        "uq_seat_commitments_one_active", "seat_commitments", ["subscription_id"], unique=True,
        postgresql_where=sa.text("state = 'active'"), sqlite_where=sa.text("state = 'active'"),
    )
    op.create_index(
        "uq_seat_commitments_one_opening", "seat_commitments", ["subscription_id"], unique=True,
        postgresql_where=sa.text("origin_type = 'opening'"), sqlite_where=sa.text("origin_type = 'opening'"),
    )
    op.create_index("ix_seat_changes_subscription_state", "seat_changes", ["subscription_id", "state", "effective_at"])
    op.create_index(
        "uq_seat_changes_one_active_reduction", "seat_changes", ["subscription_id"], unique=True,
        postgresql_where=sa.text(f"state IN ({ACTIVE_STATES})"),
        sqlite_where=sa.text(f"state IN ({ACTIVE_STATES})"),
    )
    op.create_index("ix_seat_change_events_change_created", "seat_change_events", ["seat_change_id", "created_at", "id"])
    op.create_index("ix_seat_funding_attributions_subscription_term", "seat_funding_attributions", ["subscription_id", "term_starts_at", "id"])
    op.create_index("ix_seat_term_fundings_subscription_term", "seat_term_fundings", ["subscription_id", "term_starts_at", "id"])
    op.create_index(
        "uq_seat_term_fundings_one_renewal", "seat_term_fundings", ["subscription_id", "term_starts_at"], unique=True,
        postgresql_where=sa.text("purpose = 'renewal'"), sqlite_where=sa.text("purpose = 'renewal'"),
    )
    op.create_index(
        "uq_seat_term_fundings_new_commitment", "seat_term_fundings", ["commitment_id"], unique=True,
        postgresql_where=sa.text("purpose IN ('opening','increase')"),
        sqlite_where=sa.text("purpose IN ('opening','increase')"),
    )
    op.create_index("ix_seat_funding_uses_term_funding", "seat_funding_uses", ["term_funding_id"])


def _postgresql_guards():
    op.execute(f"""
    CREATE FUNCTION phase8_paid_occupancy(p_org text) RETURNS integer AS $$
      SELECT count(*)::integer FROM organization_members m
      WHERE m.organization_id=p_org AND m.status='active'
        AND lower(trim(m.role)) IN ({PAID_ROLE_SQL});
    $$ LANGUAGE sql STABLE;

    -- The grant must belong to the named actor, to this billing account, be an
    -- active billing owner/admin grant at the authorization time, and not have
    -- ended before now (no backdating into an expired window). No NULL actor.
    -- Occupancy decisions: READ COMMITTED only, then lock the organization row
    -- (waits for/blocks member inserts via their FK key-share lock) and its
    -- member rows (waits for/blocks role updates) before counting in a new
    -- statement. Membership is only read and locked, never written.
    CREATE FUNCTION phase8_decision_occupancy(p_org text) RETURNS integer AS $$
    DECLARE result integer;
    BEGIN
      IF current_setting('transaction_isolation')<>'read committed' THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat occupancy decisions require READ COMMITTED isolation';
      END IF;
      PERFORM 1 FROM organizations WHERE id=p_org FOR UPDATE;
      PERFORM 1 FROM organization_members WHERE organization_id=p_org ORDER BY id FOR SHARE;
      result := phase8_paid_occupancy(p_org);
      RETURN result;
    END; $$ LANGUAGE plpgsql;

    CREATE FUNCTION phase8_grant_ok(p_grant text, p_account text, p_actor text, p_at timestamptz) RETURNS boolean AS $$
      SELECT p_actor IS NOT NULL AND p_grant IS NOT NULL AND EXISTS (
        SELECT 1 FROM billing_role_grants g
        WHERE g.id=p_grant AND g.billing_account_id=p_account AND g.user_id=p_actor
          AND g.role IN ('billing_owner','billing_admin') AND g.state='active'
          AND g.starts_at<=p_at AND (g.ends_at IS NULL OR (p_at<g.ends_at AND now()<g.ends_at))
      );
    $$ LANGUAGE sql STABLE;

    CREATE FUNCTION phase8_paid_line_ok(p_line text, p_account text, p_subscription text, p_kinds text[]) RETURNS boolean AS $$
      SELECT EXISTS (
        SELECT 1 FROM financial_lines l JOIN financial_transactions f ON f.id=l.financial_transaction_id
        JOIN billing_accounts a ON a.id=f.billing_account_id
        WHERE l.id=p_line AND l.subscription_id=p_subscription AND l.line_kind=ANY(p_kinds)
          AND l.principal_minor>0 AND f.kind='payment' AND f.principal_minor>0
          AND f.billing_account_id=p_account AND f.currency=a.currency AND l.currency=f.currency
      );
    $$ LANGUAGE sql STABLE;

    CREATE FUNCTION phase8_line_paid_at(p_line text) RETURNS timestamptz AS $$
      SELECT f.effective_at FROM financial_lines l JOIN financial_transactions f ON f.id=l.financial_transaction_id
      WHERE l.id=p_line;
    $$ LANGUAGE sql STABLE;

    CREATE FUNCTION phase8_event_ok(p_event text, p_account text, p_type text, p_aggregate_type text, p_aggregate text) RETURNS boolean AS $$
      SELECT EXISTS (
        SELECT 1 FROM domain_events e JOIN communication_outbox o ON o.domain_event_id=e.id
        WHERE e.id=p_event AND e.billing_account_id=p_account AND e.event_type=p_type
          AND e.aggregate_type=p_aggregate_type AND e.aggregate_id=p_aggregate
          AND o.billing_account_id=p_account
      );
    $$ LANGUAGE sql STABLE;

    -- Concurrency-only fence (Phase 5.3 pattern). Every Phase 8 insert flips
    -- it, so a REPEATABLE READ/SERIALIZABLE writer whose snapshot predates
    -- committed seat history for the subscription fails with 40001 instead of
    -- acting on stale state. It records no seat quantity or state.
    CREATE FUNCTION phase8_flip_fence(p_subscription text) RETURNS void AS $$
    BEGIN
      INSERT INTO seat_commitment_fences (subscription_id) VALUES (p_subscription) ON CONFLICT DO NOTHING;
      UPDATE seat_commitment_fences SET fence_bit = NOT fence_bit WHERE subscription_id=p_subscription;
    END; $$ LANGUAGE plpgsql;

    CREATE FUNCTION phase8_fence_guard() RETURNS trigger AS $$
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat fences are permanent'; END IF;
      IF TG_OP='UPDATE' AND NEW.subscription_id IS DISTINCT FROM OLD.subscription_id THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat fence identity is immutable';
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase8_fence_guard BEFORE UPDATE OR DELETE ON seat_commitment_fences
      FOR EACH ROW EXECUTE FUNCTION phase8_fence_guard();

    CREATE FUNCTION phase8_commitment_guard() RETURNS trigger AS $$
    DECLARE s billing_subscriptions%ROWTYPE; previous seat_commitments%ROWTYPE; expected_namespace text;
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat commitments are historical records'; END IF;
      IF TG_OP='UPDATE' THEN
        IF NEW.id IS DISTINCT FROM OLD.id OR NEW.billing_account_id IS DISTINCT FROM OLD.billing_account_id
          OR NEW.subscription_id IS DISTINCT FROM OLD.subscription_id OR NEW.quantity IS DISTINCT FROM OLD.quantity
          OR NEW.origin_type IS DISTINCT FROM OLD.origin_type OR NEW.starts_at IS DISTINCT FROM OLD.starts_at
          OR NEW.previous_commitment_id IS DISTINCT FROM OLD.previous_commitment_id
          OR NEW.idempotency_registry_id IS DISTINCT FROM OLD.idempotency_registry_id
          OR NEW.domain_event_id IS DISTINCT FROM OLD.domain_event_id OR NEW.created_at IS DISTINCT FROM OLD.created_at
          OR NOT (OLD.state='active' AND NEW.state='replaced' AND OLD.ends_at IS NULL AND NEW.ends_at IS NOT NULL)
        THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat commitment can only be closed once by its successor'; END IF;
        RETURN NEW;
      END IF;
      PERFORM phase8_flip_fence(NEW.subscription_id);
      SELECT * INTO s FROM billing_subscriptions WHERE id=NEW.subscription_id FOR SHARE;
      expected_namespace := CASE NEW.origin_type WHEN 'opening' THEN 'seat_commitment_opening'
        WHEN 'increase' THEN 'seat_command' ELSE 'seat_transition' END;
      IF NEW.state<>'active' OR NEW.ends_at IS NOT NULL
        OR s.id IS NULL OR s.billing_account_id<>NEW.billing_account_id
        OR NOT EXISTS (SELECT 1 FROM idempotency_registry r WHERE r.id=NEW.idempotency_registry_id
             AND r.namespace=expected_namespace AND r.state='claimed')
        OR NOT phase8_event_ok(NEW.domain_event_id, NEW.billing_account_id,
             CASE NEW.origin_type WHEN 'opening' THEN 'seat_commitment_opened' ELSE 'seat_change_applied' END,
             CASE NEW.origin_type WHEN 'opening' THEN 'seat_commitment' ELSE 'seat_change' END,
             (SELECT aggregate_id FROM domain_events WHERE id=NEW.domain_event_id))
        OR (NEW.origin_type='opening' AND (
             (SELECT aggregate_id FROM domain_events WHERE id=NEW.domain_event_id)<>NEW.id
             OR s.state NOT IN ('active','past_due')
             OR EXISTS (SELECT 1 FROM seat_commitments c WHERE c.subscription_id=NEW.subscription_id)))
      THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat commitment lacks matching authority or communication evidence'; END IF;
      IF NEW.origin_type<>'opening' THEN
        SELECT * INTO previous FROM seat_commitments WHERE id=NEW.previous_commitment_id;
        IF previous.id IS NULL OR previous.subscription_id<>NEW.subscription_id
          OR previous.billing_account_id<>NEW.billing_account_id
          OR previous.state<>'replaced' OR previous.ends_at<>NEW.starts_at
        THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat commitment must directly succeed the replaced interval'; END IF;
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase8_commitment_guard BEFORE INSERT OR UPDATE OR DELETE ON seat_commitments
      FOR EACH ROW EXECUTE FUNCTION phase8_commitment_guard();

    CREATE FUNCTION phase8_commitment_final() RETURNS trigger AS $$
    DECLARE c seat_commitments%ROWTYPE; previous seat_commitments%ROWTYPE;
    BEGIN
      SELECT * INTO c FROM seat_commitments WHERE id=NEW.id;
      IF c.state='replaced' AND NOT EXISTS (
          SELECT 1 FROM seat_commitments n WHERE n.previous_commitment_id=c.id AND n.starts_at=c.ends_at)
      THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='a closed seat commitment requires its successor'; END IF;
      SELECT * INTO previous FROM seat_commitments WHERE id=c.previous_commitment_id;
      IF c.origin_type='opening' AND NOT EXISTS (
          SELECT 1 FROM idempotency_registry r WHERE r.id=c.idempotency_registry_id AND r.state='completed'
            AND r.result_type='seat_commitment' AND r.result_id=c.id)
      THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat commitment opening is incomplete'; END IF;
      IF NOT EXISTS (
          SELECT 1 FROM seat_term_fundings f
          WHERE f.commitment_id=c.id AND f.state='funded' AND f.subscription_id=c.subscription_id
            AND ((c.origin_type='opening' AND f.purpose='opening' AND f.term_starts_at=c.starts_at
                  AND f.required_seats=c.quantity)
              OR (c.origin_type='increase' AND f.purpose='increase' AND f.term_starts_at=c.starts_at
                  AND f.required_seats=c.quantity-previous.quantity)
              OR (c.origin_type='reduction' AND f.purpose='renewal' AND f.term_starts_at<=c.starts_at
                  AND f.required_seats=c.quantity)))
      THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='a new seat commitment requires funding for its full quantity'; END IF;
      IF c.origin_type='increase' AND NOT EXISTS (
          SELECT 1 FROM seat_changes x WHERE x.result_commitment_id=c.id AND x.kind='increase'
            AND x.state='increased' AND x.base_commitment_id=c.previous_commitment_id
            AND x.base_quantity=previous.quantity AND x.target_quantity=c.quantity
            AND x.effective_at=c.starts_at
            AND x.idempotency_registry_id=c.idempotency_registry_id AND x.domain_event_id=c.domain_event_id)
      THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat increase commitment lacks its paid command'; END IF;
      IF c.origin_type='reduction' AND NOT EXISTS (
          SELECT 1 FROM seat_change_events e JOIN seat_changes x ON x.id=e.seat_change_id
          WHERE e.result_commitment_id=c.id AND e.to_state='reduced'
            AND e.effective_at=c.starts_at AND e.idempotency_registry_id=c.idempotency_registry_id
            AND e.domain_event_id=c.domain_event_id AND x.kind='reduction' AND x.state='reduced'
            AND x.base_commitment_id=c.previous_commitment_id AND x.target_quantity=c.quantity
            AND c.quantity<previous.quantity)
      THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat reduction commitment lacks its renewal transition'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE CONSTRAINT TRIGGER trg_phase8_commitment_final AFTER INSERT OR UPDATE ON seat_commitments
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION phase8_commitment_final();

    CREATE FUNCTION phase8_change_guard() RETURNS trigger AS $$
    DECLARE s billing_subscriptions%ROWTYPE; a billing_accounts%ROWTYPE; base seat_commitments%ROWTYPE;
      result seat_commitments%ROWTYPE; e seat_change_events%ROWTYPE; prefix text; occupancy integer;
    BEGIN
      IF TG_OP='DELETE' THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat changes are historical records'; END IF;
      IF TG_OP='UPDATE' THEN
        IF NEW.id IS DISTINCT FROM OLD.id OR NEW.billing_account_id IS DISTINCT FROM OLD.billing_account_id
          OR NEW.subscription_id IS DISTINCT FROM OLD.subscription_id OR NEW.kind IS DISTINCT FROM OLD.kind
          OR NEW.base_commitment_id IS DISTINCT FROM OLD.base_commitment_id
          OR NEW.base_quantity IS DISTINCT FROM OLD.base_quantity OR NEW.target_quantity IS DISTINCT FROM OLD.target_quantity
          OR NEW.seat_delta IS DISTINCT FROM OLD.seat_delta OR NEW.occupancy_at_request IS DISTINCT FROM OLD.occupancy_at_request
          OR NEW.requested_at IS DISTINCT FROM OLD.requested_at
          OR NEW.authorizing_role_grant_id IS DISTINCT FROM OLD.authorizing_role_grant_id
          OR NEW.requested_by_user_id IS DISTINCT FROM OLD.requested_by_user_id
          OR NEW.command_key IS DISTINCT FROM OLD.command_key OR NEW.request_fingerprint IS DISTINCT FROM OLD.request_fingerprint
          OR NEW.idempotency_registry_id IS DISTINCT FROM OLD.idempotency_registry_id
          OR NEW.domain_event_id IS DISTINCT FROM OLD.domain_event_id
          OR NEW.supersedes_change_id IS DISTINCT FROM OLD.supersedes_change_id OR NEW.created_at IS DISTINCT FROM OLD.created_at
        THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat change identity and evidence are immutable'; END IF;
        IF NEW.state IS DISTINCT FROM OLD.state OR NEW.last_event_id IS DISTINCT FROM OLD.last_event_id
          OR NEW.effective_at IS DISTINCT FROM OLD.effective_at
          OR NEW.result_commitment_id IS DISTINCT FROM OLD.result_commitment_id THEN
          SELECT * INTO e FROM seat_change_events WHERE id=NEW.last_event_id;
          IF e.id IS NULL OR NEW.last_event_id IS NOT DISTINCT FROM OLD.last_event_id
            OR e.seat_change_id<>NEW.id OR e.from_state<>OLD.state OR e.to_state<>NEW.state
            OR NEW.effective_at IS DISTINCT FROM COALESCE(e.target_effective_at, OLD.effective_at)
            OR NEW.result_commitment_id IS DISTINCT FROM COALESCE(e.result_commitment_id, OLD.result_commitment_id)
          THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat change state requires an append-only event'; END IF;
        END IF;
        RETURN NEW;
      END IF;
      PERFORM phase8_flip_fence(NEW.subscription_id);
      SELECT * INTO s FROM billing_subscriptions WHERE id=NEW.subscription_id FOR SHARE;
      SELECT * INTO a FROM billing_accounts WHERE id=NEW.billing_account_id;
      SELECT * INTO base FROM seat_commitments WHERE id=NEW.base_commitment_id;
      prefix := 'seat:' || a.organization_id || ':';
      IF NEW.last_event_id IS NOT NULL OR s.id IS NULL OR a.id IS NULL OR s.billing_account_id<>NEW.billing_account_id
        OR s.state IN ('cancelled','expired')
        OR left(NEW.command_key, length(prefix))<>prefix OR length(NEW.command_key)<=length(prefix)
        OR NOT EXISTS (SELECT 1 FROM idempotency_registry r WHERE r.id=NEW.idempotency_registry_id
             AND r.namespace='seat_command' AND r.key=NEW.command_key
             AND r.request_fingerprint=NEW.request_fingerprint AND r.state='claimed')
        OR NOT phase8_grant_ok(NEW.authorizing_role_grant_id, NEW.billing_account_id, NEW.requested_by_user_id, NEW.requested_at)
        OR NOT phase8_event_ok(NEW.domain_event_id, NEW.billing_account_id,
             CASE NEW.state WHEN 'increased' THEN 'seat_change_applied' WHEN 'blocked_occupancy' THEN 'seat_reduction_blocked'
               ELSE 'seat_change_scheduled' END, 'seat_change', NEW.id)
        OR base.id IS NULL OR base.subscription_id<>NEW.subscription_id OR base.quantity<>NEW.base_quantity
      THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat change lacks matching authority, permission, or communication evidence'; END IF;
      IF NEW.kind='increase' THEN
        SELECT * INTO result FROM seat_commitments WHERE id=NEW.result_commitment_id;
        IF NEW.state<>'increased' OR s.state NOT IN ('active','past_due')
          OR NEW.effective_at<s.term_starts_at OR NEW.effective_at>=s.term_ends_at
          -- Founder decision: only a billing owner authorizes new seat spending.
          OR NOT EXISTS (SELECT 1 FROM billing_role_grants g WHERE g.id=NEW.authorizing_role_grant_id
               AND g.role='billing_owner')
          OR base.state<>'replaced' OR base.ends_at<>NEW.effective_at
          OR result.id IS NULL OR result.state<>'active' OR result.origin_type<>'increase'
          OR result.previous_commitment_id<>base.id OR result.quantity<>NEW.target_quantity
          OR result.starts_at<>NEW.effective_at
        THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat increase lacks billing-owner authority or its new commitment'; END IF;
      ELSE
        occupancy := phase8_decision_occupancy(a.organization_id);
        IF NEW.state NOT IN ('scheduled_reduction','blocked_occupancy') OR base.state<>'active'
          OR NEW.requested_at<base.starts_at
          OR s.interval NOT IN ('month','year') OR NEW.effective_at<>s.term_ends_at
          OR NEW.occupancy_at_request<>occupancy
          OR (occupancy>NEW.target_quantity AND NEW.state<>'blocked_occupancy')
          OR (occupancy<=NEW.target_quantity AND NEW.state<>'scheduled_reduction')
        THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat reduction violates renewal or occupancy rules'; END IF;
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase8_change_guard BEFORE INSERT OR UPDATE OR DELETE ON seat_changes
      FOR EACH ROW EXECUTE FUNCTION phase8_change_guard();

    CREATE FUNCTION phase8_change_event_before() RETURNS trigger AS $$
    DECLARE x seat_changes%ROWTYPE; s billing_subscriptions%ROWTYPE; a billing_accounts%ROWTYPE;
      result seat_commitments%ROWTYPE; allowed boolean; occupancy integer; funding seat_term_fundings%ROWTYPE;
    BEGIN
      SELECT * INTO x FROM seat_changes WHERE id=NEW.seat_change_id FOR UPDATE;
      IF x.id IS NOT NULL THEN PERFORM phase8_flip_fence(x.subscription_id); END IF;
      SELECT * INTO s FROM billing_subscriptions WHERE id=x.subscription_id;
      SELECT * INTO a FROM billing_accounts WHERE id=x.billing_account_id;
      allowed := CASE x.state
        WHEN 'scheduled_reduction' THEN NEW.to_state IN ('awaiting_payment','reduced','blocked_occupancy','cancelled','superseded')
        WHEN 'blocked_occupancy' THEN NEW.to_state IN ('scheduled_reduction','cancelled','superseded')
        WHEN 'awaiting_payment' THEN NEW.to_state IN ('reduced','blocked_occupancy','cancelled','superseded')
        ELSE false END;
      IF x.id IS NULL OR NEW.from_state<>x.state OR NOT allowed
        OR NOT EXISTS (SELECT 1 FROM idempotency_registry r WHERE r.id=NEW.idempotency_registry_id
             AND r.namespace='seat_transition' AND r.state='claimed'
             AND r.key='seat-transition:' || x.id || ':' || COALESCE(x.last_event_id,'created') || ':' || NEW.to_state)
        OR NOT phase8_event_ok(NEW.domain_event_id, x.billing_account_id,
             CASE NEW.to_state WHEN 'scheduled_reduction' THEN 'seat_change_scheduled'
               WHEN 'blocked_occupancy' THEN 'seat_reduction_blocked'
               WHEN 'awaiting_payment' THEN 'seat_change_awaiting_payment'
               WHEN 'reduced' THEN 'seat_change_applied'
               WHEN 'cancelled' THEN 'seat_change_cancelled' ELSE 'seat_change_superseded' END,
             'seat_change', x.id)
        OR (NEW.to_state IN ('cancelled','superseded','scheduled_reduction') AND (NEW.actor_type<>'user'
             OR NOT phase8_grant_ok(NEW.authorizing_role_grant_id, x.billing_account_id, NEW.actor_id, NEW.effective_at)))
        OR (NEW.to_state IN ('awaiting_payment','reduced','blocked_occupancy') AND NEW.actor_type<>'system')
        OR (NEW.to_state<>'scheduled_reduction' AND NEW.target_effective_at IS NOT NULL)
      THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat change event violates transition, permission, or communication contract'; END IF;
      IF NEW.to_state IN ('scheduled_reduction','blocked_occupancy','reduced') THEN
        occupancy := phase8_decision_occupancy(a.organization_id);
      END IF;
      IF NEW.to_state='scheduled_reduction' AND (
          NEW.occupancy_observed IS DISTINCT FROM occupancy OR occupancy>x.target_quantity
          OR s.interval NOT IN ('month','year') OR NEW.target_effective_at IS DISTINCT FROM s.term_ends_at
          OR s.term_ends_at<=NEW.effective_at OR s.state IN ('cancelled','expired')
          OR NOT EXISTS (SELECT 1 FROM seat_commitments c WHERE c.id=x.base_commitment_id AND c.state='active'))
      THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='resolved seat reduction requires compatible occupancy'; END IF;
      IF NEW.to_state IN ('awaiting_payment','blocked_occupancy','reduced') AND NEW.effective_at<x.effective_at
      THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='renewal outcome cannot precede the effective renewal'; END IF;
      IF NEW.to_state IN ('blocked_occupancy','reduced') THEN
        SELECT * INTO funding FROM seat_term_fundings WHERE id=NEW.term_funding_id;
        IF funding.id IS NULL OR funding.purpose<>'renewal' OR funding.subscription_id<>x.subscription_id
          OR funding.term_starts_at<>x.effective_at OR NEW.occupancy_observed IS DISTINCT FROM occupancy
          OR (NEW.to_state='reduced' AND (funding.commitment_id<>NEW.result_commitment_id
               OR funding.state<>'funded' OR funding.required_seats<>x.target_quantity))
          OR (NEW.to_state='blocked_occupancy' AND (funding.commitment_id<>x.base_commitment_id
               OR funding.required_seats<>x.base_quantity))
        THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='renewal outcome requires its matching term funding'; END IF;
      END IF;
      IF NEW.to_state='blocked_occupancy' AND occupancy<=x.target_quantity
      THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat reduction is blocked only by incompatible occupancy'; END IF;
      IF NEW.to_state='reduced' THEN
        SELECT * INTO result FROM seat_commitments WHERE id=NEW.result_commitment_id;
        IF occupancy>x.target_quantity OR result.id IS NULL OR result.state<>'active'
          OR result.origin_type<>'reduction' OR result.previous_commitment_id<>x.base_commitment_id
          OR result.quantity<>x.target_quantity OR result.starts_at<>NEW.effective_at
          OR result.subscription_id<>x.subscription_id
        THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat reduction requires compatible occupancy and its new commitment'; END IF;
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase8_change_event_before BEFORE INSERT ON seat_change_events
      FOR EACH ROW EXECUTE FUNCTION phase8_change_event_before();

    CREATE FUNCTION phase8_change_event_after() RETURNS trigger AS $$
    BEGIN
      UPDATE seat_changes SET state=NEW.to_state, last_event_id=NEW.id,
        effective_at=COALESCE(NEW.target_effective_at, effective_at),
        result_commitment_id=COALESCE(NEW.result_commitment_id, result_commitment_id)
      WHERE id=NEW.seat_change_id;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase8_change_event_after AFTER INSERT ON seat_change_events
      FOR EACH ROW EXECUTE FUNCTION phase8_change_event_after();

    -- Seat funding contract v1. An attribution states, once per paid line,
    -- the seats it supports for one paid term: included seats only from the
    -- approved plan definition's capabilities.included_seats; purchased seats
    -- only from a paid seat line. FinancialLine.quantity is never read.
    CREATE FUNCTION phase8_attribution_guard() RETURNS trigger AS $$
    DECLARE s billing_subscriptions%ROWTYPE; d entitlement_definitions%ROWTYPE; months integer;
      next_end timestamptz; paid_at timestamptz; declared jsonb;
    BEGIN
      IF TG_OP<>'INSERT' THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat funding attributions are immutable'; END IF;
      PERFORM phase8_flip_fence(NEW.subscription_id);
      SELECT * INTO s FROM billing_subscriptions WHERE id=NEW.subscription_id FOR SHARE;
      months := CASE s.interval WHEN 'month' THEN 1 WHEN 'year' THEN 12 ELSE NULL END;
      next_end := phase4_add_months(s.term_ends_at, months);
      paid_at := phase8_line_paid_at(NEW.financial_line_id);
      IF s.id IS NULL OR s.billing_account_id<>NEW.billing_account_id OR months IS NULL
        OR NOT EXISTS (SELECT 1 FROM idempotency_registry r WHERE r.id=NEW.idempotency_registry_id
             AND r.namespace='seat_funding_attribution' AND r.key='seat-funding:' || NEW.financial_line_id
             AND r.state='claimed')
        OR NOT phase8_paid_line_ok(NEW.financial_line_id, NEW.billing_account_id, NEW.subscription_id,
             CASE NEW.seat_source WHEN 'included' THEN ARRAY['subscription'] ELSE ARRAY['seat'] END)
        OR NOT ((NEW.term_ends_at=s.term_ends_at AND NEW.term_starts_at>=s.term_starts_at
                 AND NEW.term_starts_at<s.term_ends_at)
             OR (NEW.term_starts_at=s.term_ends_at AND NEW.term_ends_at=next_end))
        OR NOT ((paid_at>=NEW.term_starts_at AND paid_at<NEW.term_ends_at)
             OR (NEW.term_starts_at=s.term_ends_at AND paid_at>=s.term_starts_at AND paid_at<=NEW.term_starts_at))
      THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat funding lacks matching paid-line and term evidence'; END IF;
      IF NEW.seat_source='included' THEN
        SELECT * INTO d FROM entitlement_definitions WHERE id=NEW.entitlement_definition_id;
        declared := d.capability_json::jsonb #> '{{capabilities,included_seats}}';
        IF d.id IS NULL OR d.id<>s.current_entitlement_definition_id OR d.approved_at IS NULL
          OR d.approval_evidence_reference IS NULL OR declared IS NULL OR jsonb_typeof(declared)<>'number'
          OR declared::text !~ '^[0-9]+$' OR declared::text::bigint<>NEW.seats
          OR (NEW.term_starts_at<>s.term_starts_at AND NEW.term_starts_at<>s.term_ends_at)
        THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='included seats must match the approved plan definition'; END IF;
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase8_attribution_guard BEFORE INSERT OR UPDATE OR DELETE ON seat_funding_attributions
      FOR EACH ROW EXECUTE FUNCTION phase8_attribution_guard();

    CREATE FUNCTION phase8_term_funding_guard() RETURNS trigger AS $$
    DECLARE c seat_commitments%ROWTYPE; previous seat_commitments%ROWTYPE; prior seat_term_fundings%ROWTYPE;
    BEGIN
      IF TG_OP<>'INSERT' THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat term funding decisions are immutable'; END IF;
      PERFORM phase8_flip_fence(NEW.subscription_id);
      SELECT * INTO c FROM seat_commitments WHERE id=NEW.commitment_id;
      SELECT * INTO previous FROM seat_commitments WHERE id=c.previous_commitment_id;
      IF c.id IS NULL OR c.subscription_id<>NEW.subscription_id OR c.billing_account_id<>NEW.billing_account_id
        OR NOT EXISTS (SELECT 1 FROM idempotency_registry r WHERE r.id=NEW.idempotency_registry_id
             AND r.namespace='seat_term_funding' AND r.state='claimed'
             AND r.key LIKE 'seat-term-funding:' || NEW.subscription_id || ':%')
        OR NOT phase8_event_ok(NEW.domain_event_id, NEW.billing_account_id,
             CASE NEW.state WHEN 'funded' THEN 'seat_term_funded' ELSE 'seat_term_funding_unresolved' END,
             'seat_term_funding', NEW.id)
        OR (NEW.purpose='opening' AND (c.origin_type<>'opening' OR NEW.required_seats<>c.quantity
             OR NEW.term_starts_at<>c.starts_at))
        OR (NEW.purpose='increase' AND (c.origin_type<>'increase' OR NEW.required_seats<>c.quantity-previous.quantity
             OR NEW.term_starts_at<>c.starts_at))
        OR (NEW.purpose='renewal' AND NEW.required_seats<>c.quantity)
      THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat term funding does not match its commitment'; END IF;
      IF NEW.purpose='top_up' THEN
        SELECT * INTO prior FROM seat_term_fundings WHERE id=NEW.supersedes_funding_id;
        IF prior.id IS NULL OR prior.state<>'unresolved' OR prior.subscription_id<>NEW.subscription_id
          OR prior.commitment_id<>NEW.commitment_id OR prior.term_starts_at<>NEW.term_starts_at
          OR prior.term_ends_at<>NEW.term_ends_at OR prior.required_seats<>NEW.required_seats
          OR NEW.funded_seats<=prior.funded_seats
        THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='a top-up must extend one unresolved term funding'; END IF;
      END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase8_term_funding_guard BEFORE INSERT OR UPDATE OR DELETE ON seat_term_fundings
      FOR EACH ROW EXECUTE FUNCTION phase8_term_funding_guard();

    -- At commit: the attached attributions must add up exactly to the
    -- recorded funded seats, cover the same term, and come from allowed sources.
    CREATE FUNCTION phase8_term_funding_final() RETURNS trigger AS $$
    DECLARE total bigint; included_count integer; bad integer; prior_funded integer;
    BEGIN
      SELECT COALESCE(sum(a.seats),0),
             count(*) FILTER (WHERE a.seat_source='included'),
             count(*) FILTER (WHERE a.subscription_id<>NEW.subscription_id
                OR a.term_starts_at<>NEW.term_starts_at OR a.term_ends_at<>NEW.term_ends_at
                OR (NEW.purpose IN ('increase','top_up') AND a.seat_source<>'purchased'))
        INTO total, included_count, bad
        FROM seat_funding_uses u JOIN seat_funding_attributions a ON a.id=u.attribution_id
        WHERE u.term_funding_id=NEW.id;
      SELECT COALESCE((SELECT funded_seats FROM seat_term_fundings WHERE id=NEW.supersedes_funding_id),0) INTO prior_funded;
      IF bad>0 OR total+prior_funded<>NEW.funded_seats OR total=0
        OR (NEW.purpose IN ('opening','renewal') AND included_count<>1)
      THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat funding attributions do not support the recorded funding'; END IF;
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE CONSTRAINT TRIGGER trg_phase8_term_funding_final AFTER INSERT ON seat_term_fundings
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION phase8_term_funding_final();

    CREATE FUNCTION phase8_funding_use_guard() RETURNS trigger AS $$
    DECLARE a seat_funding_attributions%ROWTYPE; f seat_term_fundings%ROWTYPE;
    BEGIN
      IF TG_OP<>'INSERT' THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat funding uses are immutable'; END IF;
      SELECT * INTO a FROM seat_funding_attributions WHERE id=NEW.attribution_id;
      SELECT * INTO f FROM seat_term_fundings WHERE id=NEW.term_funding_id;
      IF a.id IS NULL OR f.id IS NULL OR a.subscription_id<>f.subscription_id
        OR a.billing_account_id<>f.billing_account_id
      THEN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='seat funding cannot be used across subscriptions'; END IF;
      PERFORM phase8_flip_fence(f.subscription_id);
      RETURN NEW;
    END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase8_funding_use_guard BEFORE INSERT OR UPDATE OR DELETE ON seat_funding_uses
      FOR EACH ROW EXECUTE FUNCTION phase8_funding_use_guard();

    CREATE FUNCTION phase8_reject_row_change() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Phase 8 seat evidence is immutable'; END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase8_change_event_immutable BEFORE UPDATE OR DELETE ON seat_change_events
      FOR EACH ROW EXECUTE FUNCTION phase8_reject_row_change();

    CREATE FUNCTION phase8_reject_truncate() RETURNS trigger AS $$
    BEGIN RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Phase 8 seat evidence cannot be truncated'; END; $$ LANGUAGE plpgsql;
    CREATE TRIGGER trg_phase8_commitment_no_truncate BEFORE TRUNCATE ON seat_commitments FOR EACH STATEMENT EXECUTE FUNCTION phase8_reject_truncate();
    CREATE TRIGGER trg_phase8_change_no_truncate BEFORE TRUNCATE ON seat_changes FOR EACH STATEMENT EXECUTE FUNCTION phase8_reject_truncate();
    CREATE TRIGGER trg_phase8_change_event_no_truncate BEFORE TRUNCATE ON seat_change_events FOR EACH STATEMENT EXECUTE FUNCTION phase8_reject_truncate();
    CREATE TRIGGER trg_phase8_fence_no_truncate BEFORE TRUNCATE ON seat_commitment_fences FOR EACH STATEMENT EXECUTE FUNCTION phase8_reject_truncate();
    CREATE TRIGGER trg_phase8_attribution_no_truncate BEFORE TRUNCATE ON seat_funding_attributions FOR EACH STATEMENT EXECUTE FUNCTION phase8_reject_truncate();
    CREATE TRIGGER trg_phase8_term_funding_no_truncate BEFORE TRUNCATE ON seat_term_fundings FOR EACH STATEMENT EXECUTE FUNCTION phase8_reject_truncate();
    CREATE TRIGGER trg_phase8_funding_use_no_truncate BEFORE TRUNCATE ON seat_funding_uses FOR EACH STATEMENT EXECUTE FUNCTION phase8_reject_truncate();
    """)


PG_TRIGGERS = (
    ("trg_phase8_funding_use_no_truncate", "seat_funding_uses"),
    ("trg_phase8_term_funding_no_truncate", "seat_term_fundings"),
    ("trg_phase8_attribution_no_truncate", "seat_funding_attributions"),
    ("trg_phase8_funding_use_guard", "seat_funding_uses"),
    ("trg_phase8_term_funding_final", "seat_term_fundings"),
    ("trg_phase8_term_funding_guard", "seat_term_fundings"),
    ("trg_phase8_attribution_guard", "seat_funding_attributions"),
    ("trg_phase8_fence_no_truncate", "seat_commitment_fences"),
    ("trg_phase8_fence_guard", "seat_commitment_fences"),
    ("trg_phase8_change_event_no_truncate", "seat_change_events"),
    ("trg_phase8_change_no_truncate", "seat_changes"),
    ("trg_phase8_commitment_no_truncate", "seat_commitments"),
    ("trg_phase8_change_event_immutable", "seat_change_events"),
    ("trg_phase8_change_event_after", "seat_change_events"),
    ("trg_phase8_change_event_before", "seat_change_events"),
    ("trg_phase8_change_guard", "seat_changes"),
    ("trg_phase8_commitment_final", "seat_commitments"),
    ("trg_phase8_commitment_guard", "seat_commitments"),
)
PG_FUNCTIONS = (
    "phase8_reject_truncate()", "phase8_reject_row_change()", "phase8_change_event_after()",
    "phase8_change_event_before()", "phase8_change_guard()", "phase8_commitment_final()",
    "phase8_commitment_guard()", "phase8_fence_guard()", "phase8_flip_fence(text)",
    "phase8_event_ok(text, text, text, text, text)",
    "phase8_line_paid_at(text)", "phase8_paid_line_ok(text, text, text, text[])",
    "phase8_funding_use_guard()", "phase8_term_funding_final()", "phase8_term_funding_guard()",
    "phase8_attribution_guard()", "phase8_grant_ok(text, text, text, timestamptz)",
    "phase8_decision_occupancy(text)", "phase8_paid_occupancy(text)",
)


SQLITE_TRIGGERS = (
    "trg_phase8_seat_commitments_delete", "trg_phase8_seat_changes_delete",
    "trg_phase8_seat_change_events_delete", "trg_phase8_seat_commitment_fences_delete",
    "trg_phase8_seat_funding_attributions_delete", "trg_phase8_seat_term_fundings_delete",
    "trg_phase8_seat_funding_uses_delete", "trg_phase8_seat_funding_attributions_update",
    "trg_phase8_seat_term_fundings_update", "trg_phase8_seat_funding_uses_update",
    "trg_phase8_change_event_update", "trg_phase8_commitment_update",
    "trg_phase8_change_identity_update", "trg_phase8_change_state_update",
    "trg_phase8_change_event_after",
)


def _sqlite_guards():
    for table, message in (
        ("seat_commitments", "seat commitments are historical records"),
        ("seat_changes", "seat changes are historical records"),
        ("seat_change_events", "Phase 8 seat evidence is immutable"),
        ("seat_commitment_fences", "seat fences are permanent"),
        ("seat_funding_attributions", "seat funding attributions are immutable"),
        ("seat_term_fundings", "seat term funding decisions are immutable"),
        ("seat_funding_uses", "seat funding uses are immutable"),
    ):
        op.execute(f"CREATE TRIGGER trg_phase8_{table}_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'{message}'); END")
    for table, message in (
        ("seat_funding_attributions", "seat funding attributions are immutable"),
        ("seat_term_fundings", "seat term funding decisions are immutable"),
        ("seat_funding_uses", "seat funding uses are immutable"),
    ):
        op.execute(f"CREATE TRIGGER trg_phase8_{table}_update BEFORE UPDATE ON {table} BEGIN SELECT RAISE(ABORT,'{message}'); END")
    op.execute("CREATE TRIGGER trg_phase8_change_event_update BEFORE UPDATE ON seat_change_events BEGIN SELECT RAISE(ABORT,'Phase 8 seat evidence is immutable'); END")
    # A commitment changes once: active -> replaced with an end time; nothing else.
    op.execute(
        "CREATE TRIGGER trg_phase8_commitment_update BEFORE UPDATE ON seat_commitments "
        "WHEN NEW.id IS NOT OLD.id OR NEW.billing_account_id IS NOT OLD.billing_account_id "
        "OR NEW.subscription_id IS NOT OLD.subscription_id OR NEW.quantity IS NOT OLD.quantity "
        "OR NEW.origin_type IS NOT OLD.origin_type OR NEW.starts_at IS NOT OLD.starts_at "
        "OR NEW.previous_commitment_id IS NOT OLD.previous_commitment_id "
        "OR NEW.idempotency_registry_id IS NOT OLD.idempotency_registry_id "
        "OR NEW.domain_event_id IS NOT OLD.domain_event_id OR NEW.created_at IS NOT OLD.created_at "
        "OR NOT (OLD.state='active' AND NEW.state='replaced' AND OLD.ends_at IS NULL AND NEW.ends_at IS NOT NULL) "
        "BEGIN SELECT RAISE(ABORT,'seat commitment can only be closed once by its successor'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_phase8_change_identity_update BEFORE UPDATE ON seat_changes "
        "WHEN NEW.id IS NOT OLD.id OR NEW.billing_account_id IS NOT OLD.billing_account_id "
        "OR NEW.subscription_id IS NOT OLD.subscription_id OR NEW.kind IS NOT OLD.kind "
        "OR NEW.base_commitment_id IS NOT OLD.base_commitment_id "
        "OR NEW.base_quantity IS NOT OLD.base_quantity OR NEW.target_quantity IS NOT OLD.target_quantity "
        "OR NEW.seat_delta IS NOT OLD.seat_delta OR NEW.occupancy_at_request IS NOT OLD.occupancy_at_request "
        "OR NEW.requested_at IS NOT OLD.requested_at "
        "OR NEW.authorizing_role_grant_id IS NOT OLD.authorizing_role_grant_id "
        "OR NEW.requested_by_user_id IS NOT OLD.requested_by_user_id "
        "OR NEW.command_key IS NOT OLD.command_key OR NEW.request_fingerprint IS NOT OLD.request_fingerprint "
        "OR NEW.idempotency_registry_id IS NOT OLD.idempotency_registry_id "
        "OR NEW.domain_event_id IS NOT OLD.domain_event_id "
        "OR NEW.supersedes_change_id IS NOT OLD.supersedes_change_id OR NEW.created_at IS NOT OLD.created_at "
        "BEGIN SELECT RAISE(ABORT,'seat change identity and evidence are immutable'); END"
    )
    # State projection columns change only from a matching append-only event.
    op.execute(
        "CREATE TRIGGER trg_phase8_change_state_update BEFORE UPDATE ON seat_changes "
        "WHEN (NEW.state IS NOT OLD.state OR NEW.last_event_id IS NOT OLD.last_event_id "
        "OR NEW.effective_at IS NOT OLD.effective_at OR NEW.result_commitment_id IS NOT OLD.result_commitment_id) "
        "AND NOT EXISTS (SELECT 1 FROM seat_change_events e WHERE e.id=NEW.last_event_id "
        "AND NEW.last_event_id IS NOT OLD.last_event_id AND e.seat_change_id=NEW.id "
        "AND e.from_state=OLD.state AND e.to_state=NEW.state "
        "AND NEW.effective_at IS COALESCE(e.target_effective_at, OLD.effective_at) "
        "AND NEW.result_commitment_id IS COALESCE(e.result_commitment_id, OLD.result_commitment_id)) "
        "BEGIN SELECT RAISE(ABORT,'seat change state requires an append-only event'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_phase8_change_event_after AFTER INSERT ON seat_change_events BEGIN "
        "UPDATE seat_changes SET state=NEW.to_state, last_event_id=NEW.id, "
        "effective_at=COALESCE(NEW.target_effective_at, effective_at), "
        "result_commitment_id=COALESCE(NEW.result_commitment_id, result_commitment_id) "
        "WHERE id=NEW.seat_change_id; END"
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
            raise Phase8EvidenceNotEmptyError("Phase 8 downgrade refuses to discard seat evidence")
    if bind.dialect.name == "postgresql":
        for trigger, table in PG_TRIGGERS:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))
        for function in PG_FUNCTIONS:
            op.execute(sa.text(f"DROP FUNCTION IF EXISTS {function}"))
    else:
        for trigger in SQLITE_TRIGGERS:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))
    op.drop_index("ix_seat_funding_uses_term_funding", table_name="seat_funding_uses")
    op.drop_index("uq_seat_term_fundings_new_commitment", table_name="seat_term_fundings")
    op.drop_index("uq_seat_term_fundings_one_renewal", table_name="seat_term_fundings")
    op.drop_index("ix_seat_term_fundings_subscription_term", table_name="seat_term_fundings")
    op.drop_index("ix_seat_funding_attributions_subscription_term", table_name="seat_funding_attributions")
    op.drop_index("ix_seat_change_events_change_created", table_name="seat_change_events")
    op.drop_index("uq_seat_changes_one_active_reduction", table_name="seat_changes")
    op.drop_index("ix_seat_changes_subscription_state", table_name="seat_changes")
    op.drop_index("uq_seat_commitments_one_opening", table_name="seat_commitments")
    op.drop_index("uq_seat_commitments_one_active", table_name="seat_commitments")
    op.drop_index("ix_seat_commitments_subscription_starts", table_name="seat_commitments")
    op.drop_table("seat_change_events")
    op.drop_table("seat_funding_uses")
    op.drop_table("seat_term_fundings")
    op.drop_table("seat_funding_attributions")
    op.drop_table("seat_changes")
    op.drop_table("seat_commitments")
    op.drop_table("seat_commitment_fences")
