"""Add inactive Phase 10 trial, promotion, comp, and internal-funding evidence.

Revision ID: f2b4d6e8a0c3
Revises: e1a3c5b7d9f2

Additive tables plus one approved gate change: Phase 4 kept trial, promotion,
and comp entitlement instances in ``proposed``/``cancelled`` until "their
later authoritative phases supply the approved evidence". This revision
narrows that check to enterprise contracts (Phase 11) and replaces it with a
database guard that lets trial, promotion, comp, and internal instances leave
``proposed`` only with a Phase 10 offer-redemption record.
"""

from alembic import op
import sqlalchemy as sa


revision = "f2b4d6e8a0c3"
down_revision = "e1a3c5b7d9f2"
branch_labels = None
depends_on = None


TABLES = (
    "credit_offer_fundings", "credit_offer_redemptions",
    "billing_staff_permission_revocations", "billing_staff_permission_grants",
)
GATE_NAME = "ck_entitlement_instances_later_authority_gate"
OLD_GATE = "source_type NOT IN ('trial','promotion','comp','enterprise_contract') OR state IN ('proposed','cancelled')"
NEW_GATE = "source_type <> 'enterprise_contract' OR state IN ('proposed','cancelled')"
OFFER_LOT_SOURCES = "'trial','promotional','comp','internal'"
OFFER_ENTITLEMENT_SOURCES = "'trial','promotion','comp','internal'"


class Phase10EvidenceNotEmptyError(RuntimeError):
    pass


def _ts(name, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def _created():
    return sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now())


def _create_tables():
    op.create_table(
        "billing_staff_permission_grants",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("user_id", sa.String(36), nullable=False),
        sa.Column("permission", sa.String(64), nullable=False),
        sa.Column("permission_version", sa.Integer(), nullable=False),
        _ts("starts_at"), _ts("ends_at", True),
        sa.Column("grant_key", sa.String(255), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("approval_evidence_reference", sa.String(255), nullable=False),
        sa.Column("justification", sa.Text(), nullable=False),
        sa.Column("idempotency_registry_id", sa.String(36), nullable=False),
        sa.Column("actor_type", sa.String(40), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        _created(),
        sa.CheckConstraint(
            "permission IN ('billing.comp.grant', 'billing.internal_funding.grant')",
            name="ck_billing_staff_permission_grants_permission",
        ),
        sa.CheckConstraint("permission_version = 1", name="ck_billing_staff_permission_grants_version"),
        sa.CheckConstraint("ends_at IS NULL OR ends_at > starts_at", name="ck_billing_staff_permission_grants_interval"),
        sa.CheckConstraint(
            "actor_type = 'system' AND length(trim(actor_id)) > 0 "
            "AND length(trim(grant_key)) > 0 "
            "AND length(trim(approval_evidence_reference)) > 0 AND length(trim(justification)) > 0 "
            "AND length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint)",
            name="ck_billing_staff_permission_grants_provenance",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_billing_staff_permission_grants_user", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["idempotency_registry_id"], ["idempotency_registry.id"], name="fk_billing_staff_permission_grants_registry", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_billing_staff_permission_grants"),
        sa.UniqueConstraint("grant_key", name="uq_billing_staff_permission_grants_key"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_billing_staff_permission_grants_registry"),
    )
    op.create_index(
        "ix_billing_staff_permission_grants_user_permission", "billing_staff_permission_grants",
        ["user_id", "permission", "starts_at"],
    )

    op.create_table(
        "billing_staff_permission_revocations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("grant_id", sa.String(36), nullable=False),
        _ts("revoked_at"),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("evidence_reference", sa.String(255), nullable=False),
        sa.Column("actor_type", sa.String(40), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        _created(),
        sa.CheckConstraint(
            "actor_type = 'system' AND length(trim(actor_id)) > 0 "
            "AND length(trim(reason)) > 0 AND length(trim(evidence_reference)) > 0",
            name="ck_billing_staff_permission_revocations_provenance",
        ),
        sa.ForeignKeyConstraint(["grant_id"], ["billing_staff_permission_grants.id"], name="fk_billing_staff_permission_revocations_grant", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_billing_staff_permission_revocations"),
        sa.UniqueConstraint("grant_id", name="uq_billing_staff_permission_revocations_grant"),
    )

    op.create_table(
        "credit_offer_redemptions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("entitlement_definition_id", sa.String(36), nullable=False),
        sa.Column("offer_key", sa.String(80), nullable=False),
        sa.Column("offer_version", sa.Integer(), nullable=False),
        sa.Column("origin", sa.String(16), nullable=False),
        sa.Column("redemption_id", sa.String(128), nullable=False),
        sa.Column("redemption_key", sa.String(255), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("funding_source", sa.String(80), nullable=False),
        _ts("redeemed_at"), _ts("term_starts_at"), _ts("term_ends_at"),
        sa.Column("credit_amount", sa.BigInteger(), nullable=False),
        _ts("credit_expires_at", True),
        sa.Column("per_account_limit", sa.Integer(), nullable=False),
        sa.Column("total_limit", sa.Integer(), nullable=False),
        sa.Column("account_redemption_index", sa.Integer(), nullable=False),
        sa.Column("total_redemption_index", sa.Integer(), nullable=False),
        sa.Column("entitlement_instance_id", sa.String(36), nullable=True),
        sa.Column("staff_permission_grant_id", sa.String(36), nullable=True),
        sa.Column("reason_code", sa.String(64), nullable=True),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column("evidence_reference", sa.String(255), nullable=True),
        sa.Column("idempotency_registry_id", sa.String(36), nullable=False),
        sa.Column("domain_event_id", sa.String(36), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        sa.Column("actor_type", sa.String(40), nullable=False),
        sa.Column("actor_id", sa.String(255), nullable=False),
        _created(),
        sa.CheckConstraint("origin IN ('trial', 'promotion', 'comp', 'internal')", name="ck_credit_offer_redemptions_origin"),
        sa.CheckConstraint("contract_version = 1", name="ck_credit_offer_redemptions_contract"),
        sa.CheckConstraint(
            "credit_amount >= 0 AND offer_version > 0 "
            "AND per_account_limit > 0 AND total_limit > 0 "
            "AND account_redemption_index > 0 AND account_redemption_index <= per_account_limit "
            "AND total_redemption_index > 0 AND total_redemption_index <= total_limit "
            "AND account_redemption_index <= total_redemption_index",
            name="ck_credit_offer_redemptions_limits",
        ),
        sa.CheckConstraint(
            "term_starts_at = redeemed_at AND term_ends_at > term_starts_at "
            "AND (credit_expires_at IS NULL OR credit_expires_at = term_ends_at)",
            name="ck_credit_offer_redemptions_term",
        ),
        sa.CheckConstraint(
            "length(trim(redemption_id)) > 0 AND length(trim(offer_key)) > 0 "
            "AND length(trim(funding_source)) > 0 "
            "AND redemption_key = 'offer-redemption:' || entitlement_definition_id || ':' || redemption_id "
            "AND length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint) "
            "AND length(trim(actor_type)) > 0 AND length(trim(actor_id)) > 0",
            name="ck_credit_offer_redemptions_identity",
        ),
        sa.CheckConstraint(
            "(origin IN ('trial', 'promotion') AND actor_type = 'system' "
            " AND staff_permission_grant_id IS NULL) OR "
            "(origin IN ('comp', 'internal') AND actor_type = 'user' "
            " AND staff_permission_grant_id IS NOT NULL "
            " AND reason_code IS NOT NULL AND length(trim(reason_code)) > 0 "
            " AND justification IS NOT NULL AND length(trim(justification)) > 0 "
            " AND evidence_reference IS NOT NULL AND length(trim(evidence_reference)) > 0)",
            name="ck_credit_offer_redemptions_authority",
        ),
        sa.ForeignKeyConstraint(["billing_account_id"], ["billing_accounts.id"], name="fk_credit_offer_redemptions_account", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["entitlement_definition_id"], ["entitlement_definitions.id"], name="fk_credit_offer_redemptions_definition", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["entitlement_instance_id"], ["entitlement_instances.id"], name="fk_credit_offer_redemptions_instance", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["staff_permission_grant_id"], ["billing_staff_permission_grants.id"], name="fk_credit_offer_redemptions_permission", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["idempotency_registry_id"], ["idempotency_registry.id"], name="fk_credit_offer_redemptions_registry", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["domain_event_id"], ["domain_events.id"], name="fk_credit_offer_redemptions_domain_event", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_credit_offer_redemptions"),
        sa.UniqueConstraint("redemption_key", name="uq_credit_offer_redemptions_key"),
        sa.UniqueConstraint("entitlement_definition_id", "redemption_id", name="uq_credit_offer_redemptions_definition_redemption"),
        sa.UniqueConstraint("offer_key", "billing_account_id", "account_redemption_index", name="uq_credit_offer_redemptions_account_index"),
        sa.UniqueConstraint("offer_key", "total_redemption_index", name="uq_credit_offer_redemptions_total_index"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_credit_offer_redemptions_registry"),
        sa.UniqueConstraint("entitlement_instance_id", name="uq_credit_offer_redemptions_instance"),
    )
    op.create_index("ix_credit_offer_redemptions_account_redeemed", "credit_offer_redemptions", ["billing_account_id", "redeemed_at", "id"])
    op.create_index("ix_credit_offer_redemptions_domain_event", "credit_offer_redemptions", ["domain_event_id"])
    op.create_index("ix_credit_offer_redemptions_permission", "credit_offer_redemptions", ["staff_permission_grant_id"])

    op.create_table(
        "credit_offer_fundings",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("redemption_id", sa.String(36), nullable=False),
        sa.Column("billing_account_id", sa.String(36), nullable=False),
        sa.Column("funding_component", sa.String(64), nullable=False),
        sa.Column("funding_key", sa.String(512), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("credit_amount", sa.BigInteger(), nullable=False),
        sa.Column("lot_id", sa.String(36), nullable=False),
        sa.Column("grant_entry_id", sa.String(36), nullable=False),
        sa.Column("idempotency_registry_id", sa.String(36), nullable=False),
        sa.Column("contract_version", sa.Integer(), nullable=False),
        _created(),
        sa.CheckConstraint("credit_amount > 0", name="ck_credit_offer_fundings_amount"),
        sa.CheckConstraint("contract_version = 1", name="ck_credit_offer_fundings_contract"),
        sa.CheckConstraint(
            "length(trim(funding_component)) > 0 AND length(trim(funding_key)) > 0 "
            "AND length(request_fingerprint) = 64 AND request_fingerprint = lower(request_fingerprint)",
            name="ck_credit_offer_fundings_identity",
        ),
        sa.ForeignKeyConstraint(["redemption_id"], ["credit_offer_redemptions.id"], name="fk_credit_offer_fundings_redemption", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["billing_account_id"], ["billing_accounts.id"], name="fk_credit_offer_fundings_account", ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["lot_id"], ["credit_lots.id"], name="fk_credit_offer_fundings_lot", ondelete="RESTRICT", deferrable=True, initially="DEFERRED"),
        sa.ForeignKeyConstraint(["grant_entry_id"], ["credit_ledger_entries.id"], name="fk_credit_offer_fundings_grant", ondelete="RESTRICT", deferrable=True, initially="DEFERRED"),
        sa.ForeignKeyConstraint(["idempotency_registry_id"], ["idempotency_registry.id"], name="fk_credit_offer_fundings_registry", ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name="pk_credit_offer_fundings"),
        sa.UniqueConstraint("funding_key", name="uq_credit_offer_fundings_key"),
        sa.UniqueConstraint("redemption_id", "funding_component", name="uq_credit_offer_fundings_component"),
        sa.UniqueConstraint("lot_id", name="uq_credit_offer_fundings_lot"),
        sa.UniqueConstraint("grant_entry_id", name="uq_credit_offer_fundings_grant"),
        sa.UniqueConstraint("idempotency_registry_id", name="uq_credit_offer_fundings_registry"),
    )
    op.create_index("ix_credit_offer_fundings_account", "credit_offer_fundings", ["billing_account_id", "id"])


def _postgresql_guards():
    op.execute(f"ALTER TABLE entitlement_instances DROP CONSTRAINT {GATE_NAME}")
    op.execute(f"ALTER TABLE entitlement_instances ADD CONSTRAINT {GATE_NAME} CHECK ({NEW_GATE})")
    op.execute("""
    CREATE FUNCTION phase10_reject_row_change() RETURNS trigger AS $$
    BEGIN
      RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Phase 10 offer and permission evidence is immutable';
    END;
    $$ LANGUAGE plpgsql;

    CREATE FUNCTION phase10_reject_truncate() RETURNS trigger AS $$
    BEGIN
      RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='Phase 10 offer and permission evidence cannot be truncated';
    END;
    $$ LANGUAGE plpgsql;

    CREATE FUNCTION phase10_require_read_committed() RETURNS void AS $$
    BEGIN
      -- Audit F2: a REPEATABLE READ or SERIALIZABLE snapshot taken before a
      -- revocation committed would not see it. Authorization-bearing writes
      -- therefore run only in READ COMMITTED.
      IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION USING ERRCODE='25001',
          MESSAGE='offer redemption and permission revocation require READ COMMITTED';
      END IF;
    END;
    $$ LANGUAGE plpgsql;

    CREATE FUNCTION phase10_revocation_guard() RETURNS trigger AS $$
    BEGIN
      PERFORM phase10_require_read_committed();
      -- Audit F1: revocation takes effect at database time, not caller time.
      IF NEW.revoked_at IS DISTINCT FROM now() THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='permission revocation must use database time';
      END IF;
      -- Audit F2: serialize with every redemption that holds the grant.
      PERFORM 1 FROM billing_staff_permission_grants g WHERE g.id=NEW.grant_id FOR UPDATE;
      IF NOT EXISTS (SELECT 1 FROM billing_staff_permission_grants g
                     WHERE g.id=NEW.grant_id AND NEW.revoked_at >= g.starts_at) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='permission revocation must follow its grant';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE FUNCTION phase10_redemption_guard() RETURNS trigger AS $$
    DECLARE d entitlement_definitions%ROWTYPE; acct billing_accounts%ROWTYPE;
            inst entitlement_instances%ROWTYPE; g billing_staff_permission_grants%ROWTYPE;
            policy jsonb; offer jsonb; needed text; expected_event text;
    BEGIN
      PERFORM phase10_require_read_committed();
      -- Audit F1: the redemption time is the transaction time, so every term
      -- and authority check below is evaluated at database time.
      IF NEW.redeemed_at IS DISTINCT FROM now() THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='offer redemption must use database time';
      END IF;
      SELECT * INTO d FROM entitlement_definitions WHERE id=NEW.entitlement_definition_id;
      SELECT * INTO acct FROM billing_accounts WHERE id=NEW.billing_account_id;
      policy := d.funding_policy_json::jsonb;
      offer := policy->'offer';
      IF d.id IS NULL OR acct.id IS NULL OR d.approved_at IS NULL OR d.approval_evidence_reference IS NULL
         OR d.effective_at IS NULL OR d.effective_at > NEW.redeemed_at
         -- Audit R2: retirement is judged at the actual current time, not at
         -- the transaction start recorded in redeemed_at.
         OR (d.retired_at IS NOT NULL AND d.retired_at <= clock_timestamp())
         OR offer IS NULL OR jsonb_typeof(offer) <> 'object'
         OR (offer->>'schema_version') IS DISTINCT FROM '1'
         OR (policy->>'period_kind') IS DISTINCT FROM 'none'
         OR offer->>'origin' IS DISTINCT FROM NEW.origin
         OR NEW.offer_key <> d.key OR NEW.offer_version <> d.version
         OR (policy->>'credit_amount')::bigint IS DISTINCT FROM NEW.credit_amount
         OR offer->>'funding_source' IS DISTINCT FROM NEW.funding_source
         OR (offer->'owner') IS DISTINCT FROM jsonb_build_object('kind', 'billing_account')
         OR NOT COALESCE((offer->'eligibility'->'account_statuses') @> jsonb_build_array(acct.status), false)
         OR (offer->'redemption_limits'->>'per_account')::integer IS DISTINCT FROM NEW.per_account_limit
         OR (offer->'redemption_limits'->>'total')::integer IS DISTINCT FROM NEW.total_limit
         OR (offer->'term'->>'kind') IS DISTINCT FROM 'fixed_days'
         OR NEW.term_ends_at IS DISTINCT FROM
            NEW.term_starts_at + make_interval(days => (offer->'term'->>'days')::integer)
         OR COALESCE(offer->'credit_expiry'->>'kind', '') NOT IN ('term_end', 'none')
         OR (offer->'credit_expiry'->>'kind' = 'term_end' AND NEW.credit_expires_at IS DISTINCT FROM NEW.term_ends_at)
         OR (offer->'credit_expiry'->>'kind' = 'none' AND NEW.credit_expires_at IS NOT NULL) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='offer redemption must match its approved, effective offer definition';
      END IF;
      needed := CASE NEW.origin WHEN 'comp' THEN 'billing.comp.grant'
                                WHEN 'internal' THEN 'billing.internal_funding.grant' ELSE NULL END;
      IF needed IS NOT NULL THEN
        -- Lock the grant before reading revocations (conflicts with the
        -- revocation guard's FOR UPDATE), then read with this statement's
        -- READ COMMITTED snapshot.
        SELECT * INTO g FROM billing_staff_permission_grants WHERE id=NEW.staff_permission_grant_id FOR SHARE;
        IF g.id IS NULL OR NEW.actor_type <> 'user' OR g.user_id <> NEW.actor_id
           OR g.permission <> needed OR g.permission_version <> 1
           OR g.starts_at > NEW.redeemed_at
           -- Audit R2: expiry is judged at the actual current time, read
           -- after the FOR SHARE lock above is held.
           OR (g.ends_at IS NOT NULL AND g.ends_at <= clock_timestamp())
           OR EXISTS (SELECT 1 FROM billing_staff_permission_revocations r WHERE r.grant_id=g.id) THEN
          RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='comps and internal funding require an explicit, active, unrevoked staff permission';
        END IF;
      ELSIF NEW.actor_type <> 'system' OR NEW.staff_permission_grant_id IS NOT NULL THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='trials and promotions are redeemed only by the trusted offer service';
      END IF;
      IF NEW.account_redemption_index <> 1 + (SELECT count(*) FROM credit_offer_redemptions r
             WHERE r.offer_key=NEW.offer_key AND r.billing_account_id=NEW.billing_account_id)
         OR NEW.total_redemption_index <> 1 + (SELECT count(*) FROM credit_offer_redemptions r
             WHERE r.offer_key=NEW.offer_key) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='offer redemption indexes must be sequential';
      END IF;
      expected_event := CASE NEW.origin WHEN 'trial' THEN 'trial_started'
                                        WHEN 'promotion' THEN 'promotion_redeemed'
                                        WHEN 'comp' THEN 'comp_granted'
                                        ELSE 'internal_funding_granted' END;
      IF NOT EXISTS (SELECT 1 FROM idempotency_registry r WHERE r.id=NEW.idempotency_registry_id
                       AND r.namespace='credit_offer_redemption' AND r.key=NEW.redemption_key)
         OR NOT EXISTS (SELECT 1 FROM domain_events e WHERE e.id=NEW.domain_event_id
                          AND e.billing_account_id=NEW.billing_account_id
                          AND e.event_type=expected_event
                          AND e.event_key=expected_event || ':' || NEW.entitlement_definition_id || ':' || NEW.redemption_id
                          AND EXISTS (SELECT 1 FROM communication_outbox o WHERE o.domain_event_id=e.id)) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='offer redemption requires its claim and communication evidence';
      END IF;
      IF COALESCE(d.capability_json::jsonb->'capabilities', '{}'::jsonb) = '{}'::jsonb THEN
        IF NEW.entitlement_instance_id IS NOT NULL THEN
          RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='offer without capabilities cannot bind an entitlement';
        END IF;
      ELSE
        SELECT * INTO inst FROM entitlement_instances WHERE id=NEW.entitlement_instance_id;
        IF inst.id IS NULL OR inst.billing_account_id <> NEW.billing_account_id
           OR inst.entitlement_definition_id <> d.id OR inst.source_type <> NEW.origin
           OR inst.source_id <> NEW.id OR inst.starts_at <> NEW.term_starts_at
           OR inst.ends_at IS DISTINCT FROM NEW.term_ends_at
           OR inst.approval_evidence_reference IS DISTINCT FROM 'offer-redemption:' || NEW.id THEN
          RAISE EXCEPTION USING ERRCODE='23514',
            MESSAGE='offer entitlement must match the redemption term, owner, and definition';
        END IF;
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE FUNCTION phase10_redemption_final() RETURNS trigger AS $$
    DECLARE components integer; inst_state text;
    BEGIN
      -- Audit R2: re-check authority at commit with the actual current time,
      -- so no lock wait after the insert-time check can carry an expired
      -- grant, a revoked grant, or a retired offer into a commit.
      IF EXISTS (SELECT 1 FROM entitlement_definitions d WHERE d.id=NEW.entitlement_definition_id
                   AND d.retired_at IS NOT NULL AND d.retired_at <= clock_timestamp()) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='offer definition retired before the redemption committed';
      END IF;
      IF NEW.staff_permission_grant_id IS NOT NULL AND NOT EXISTS (
           SELECT 1 FROM billing_staff_permission_grants g
           WHERE g.id=NEW.staff_permission_grant_id
             AND (g.ends_at IS NULL OR g.ends_at > clock_timestamp())
             AND NOT EXISTS (SELECT 1 FROM billing_staff_permission_revocations r WHERE r.grant_id=g.id)) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='staff permission expired or was revoked before the redemption committed';
      END IF;
      SELECT COALESCE(jsonb_array_length(d.funding_policy_json::jsonb->'offer'->'components'), -1)
        INTO components FROM entitlement_definitions d WHERE d.id=NEW.entitlement_definition_id;
      IF (SELECT COALESCE(sum(f.credit_amount), 0) FROM credit_offer_fundings f WHERE f.redemption_id=NEW.id)
           <> NEW.credit_amount
         OR (SELECT count(*) FROM credit_offer_fundings f WHERE f.redemption_id=NEW.id) <> components THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='offer redemption must fund every approved component exactly once';
      END IF;
      IF NEW.entitlement_instance_id IS NOT NULL THEN
        SELECT i.state INTO inst_state FROM entitlement_instances i WHERE i.id=NEW.entitlement_instance_id;
        IF inst_state NOT IN ('active', 'expired') THEN
          RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='offer redemption must activate its entitlement';
        END IF;
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE FUNCTION phase10_funding_guard() RETURNS trigger AS $$
    DECLARE red credit_offer_redemptions%ROWTYPE;
    BEGIN
      SELECT * INTO red FROM credit_offer_redemptions WHERE id=NEW.redemption_id;
      IF red.id IS NULL OR red.billing_account_id <> NEW.billing_account_id
         OR NEW.funding_key <> 'offer:' || red.entitlement_definition_id || ':' || red.redemption_id
                               || ':' || NEW.funding_component
         OR NOT EXISTS (
           SELECT 1 FROM entitlement_definitions d,
                  jsonb_array_elements(d.funding_policy_json::jsonb->'offer'->'components') c
           WHERE d.id=red.entitlement_definition_id
             AND c->>'component'=NEW.funding_component
             AND (c->>'credit_amount')::bigint=NEW.credit_amount)
         OR NOT EXISTS (SELECT 1 FROM idempotency_registry r WHERE r.id=NEW.idempotency_registry_id
                          AND r.namespace='credit_offer_funding' AND r.key=NEW.funding_key) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='offer funding must match an approved component of its redemption';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE FUNCTION phase10_offer_lot_guard() RETURNS trigger AS $$
    BEGIN
      IF NEW.source_type NOT IN (""" + OFFER_LOT_SOURCES + """) THEN RETURN NEW; END IF;
      IF NOT EXISTS (
        SELECT 1 FROM credit_offer_fundings f JOIN credit_offer_redemptions r ON r.id=f.redemption_id
        WHERE f.id=NEW.source_id AND f.lot_id=NEW.id AND f.billing_account_id=NEW.billing_account_id
          AND r.billing_account_id=NEW.billing_account_id
          AND f.credit_amount=NEW.original_amount AND r.term_starts_at=NEW.available_at
          AND NEW.expires_at IS NOT DISTINCT FROM r.credit_expires_at
          AND NEW.member_attribution_id IS NULL AND NEW.eligibility_scope IS NULL
          AND NEW.source_type = CASE r.origin WHEN 'trial' THEN 'trial' WHEN 'promotion' THEN 'promotional'
                                              WHEN 'comp' THEN 'comp' ELSE 'internal' END) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='trial, promotional, comp, and internal lots require Phase 10 offer funding evidence';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE FUNCTION phase10_offer_grant_guard() RETURNS trigger AS $$
    DECLARE lot_row credit_lots%ROWTYPE;
    BEGIN
      IF NEW.entry_type <> 'grant' THEN RETURN NEW; END IF;
      SELECT * INTO lot_row FROM credit_lots WHERE id=NEW.lot_id;
      IF lot_row.source_type NOT IN (""" + OFFER_LOT_SOURCES + """) THEN RETURN NEW; END IF;
      IF NOT EXISTS (
        SELECT 1 FROM credit_offer_fundings f JOIN credit_offer_redemptions r ON r.id=f.redemption_id
        WHERE f.lot_id=NEW.lot_id AND f.grant_entry_id=NEW.id
          AND f.idempotency_registry_id=NEW.idempotency_registry_id
          AND f.credit_amount=NEW.available_delta AND NEW.held_delta=0
          AND NEW.effective_at=r.term_starts_at) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='offer credit grant requires Phase 10 offer funding evidence';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE FUNCTION phase10_offer_entitlement_event_guard() RETURNS trigger AS $$
    DECLARE inst entitlement_instances%ROWTYPE;
    BEGIN
      SELECT * INTO inst FROM entitlement_instances WHERE id=NEW.entitlement_instance_id;
      IF inst.source_type NOT IN (""" + OFFER_ENTITLEMENT_SOURCES + """) THEN
        RETURN NEW;
      END IF;
      -- Audit F3: the approved gate is approval to leave ``proposed``
      -- (D07). Every later state is reachable only from ``scheduled``, so
      -- gating that one transition covers activation without blocking
      -- cancellation, reduction, replacement, or expiry.
      IF NEW.from_state='proposed' AND NEW.to_state='scheduled' AND NOT EXISTS (
           SELECT 1 FROM credit_offer_redemptions r
           WHERE r.id=inst.source_id AND r.entitlement_instance_id=inst.id
             AND r.entitlement_definition_id=inst.entitlement_definition_id
             AND r.billing_account_id=inst.billing_account_id AND r.origin=inst.source_type) THEN
        RAISE EXCEPTION USING ERRCODE='23514',
          MESSAGE='trial, promotion, comp, and internal entitlements require Phase 10 redemption evidence';
      END IF;
      -- D07 ``active --(term ends)--> expired``: only at or after the term
      -- end, judged by database time. ``reducing -> expired`` follows an
      -- approved disposition and is not restricted here.
      IF NEW.from_state='active' AND NEW.to_state='expired'
         AND (NEW.effective_at < inst.ends_at OR now() < inst.ends_at) THEN
        RAISE EXCEPTION USING ERRCODE='23514', MESSAGE='offer entitlement cannot expire before its term ends';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;

    CREATE TRIGGER trg_phase10_grant_immutable BEFORE UPDATE OR DELETE ON billing_staff_permission_grants
      FOR EACH ROW EXECUTE FUNCTION phase10_reject_row_change();
    CREATE TRIGGER trg_phase10_revocation_guard BEFORE INSERT ON billing_staff_permission_revocations
      FOR EACH ROW EXECUTE FUNCTION phase10_revocation_guard();
    CREATE TRIGGER trg_phase10_revocation_immutable BEFORE UPDATE OR DELETE ON billing_staff_permission_revocations
      FOR EACH ROW EXECUTE FUNCTION phase10_reject_row_change();
    CREATE TRIGGER trg_phase10_redemption_guard BEFORE INSERT ON credit_offer_redemptions
      FOR EACH ROW EXECUTE FUNCTION phase10_redemption_guard();
    CREATE CONSTRAINT TRIGGER trg_phase10_redemption_final AFTER INSERT ON credit_offer_redemptions
      DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION phase10_redemption_final();
    CREATE TRIGGER trg_phase10_redemption_immutable BEFORE UPDATE OR DELETE ON credit_offer_redemptions
      FOR EACH ROW EXECUTE FUNCTION phase10_reject_row_change();
    CREATE TRIGGER trg_phase10_funding_guard BEFORE INSERT ON credit_offer_fundings
      FOR EACH ROW EXECUTE FUNCTION phase10_funding_guard();
    CREATE TRIGGER trg_phase10_funding_immutable BEFORE UPDATE OR DELETE ON credit_offer_fundings
      FOR EACH ROW EXECUTE FUNCTION phase10_reject_row_change();
    CREATE TRIGGER trg_phase10_offer_lot_guard BEFORE INSERT ON credit_lots
      FOR EACH ROW EXECUTE FUNCTION phase10_offer_lot_guard();
    CREATE TRIGGER trg_phase10_offer_grant_guard BEFORE INSERT ON credit_ledger_entries
      FOR EACH ROW EXECUTE FUNCTION phase10_offer_grant_guard();
    CREATE TRIGGER trg_phase10_offer_entitlement_event_guard BEFORE INSERT ON entitlement_events
      FOR EACH ROW EXECUTE FUNCTION phase10_offer_entitlement_event_guard();
    CREATE TRIGGER trg_phase10_grant_no_truncate BEFORE TRUNCATE ON billing_staff_permission_grants
      FOR EACH STATEMENT EXECUTE FUNCTION phase10_reject_truncate();
    CREATE TRIGGER trg_phase10_revocation_no_truncate BEFORE TRUNCATE ON billing_staff_permission_revocations
      FOR EACH STATEMENT EXECUTE FUNCTION phase10_reject_truncate();
    CREATE TRIGGER trg_phase10_redemption_no_truncate BEFORE TRUNCATE ON credit_offer_redemptions
      FOR EACH STATEMENT EXECUTE FUNCTION phase10_reject_truncate();
    CREATE TRIGGER trg_phase10_funding_no_truncate BEFORE TRUNCATE ON credit_offer_fundings
      FOR EACH STATEMENT EXECUTE FUNCTION phase10_reject_truncate();
    """)


PG_TRIGGERS = (
    ("trg_phase10_funding_no_truncate", "credit_offer_fundings"),
    ("trg_phase10_redemption_no_truncate", "credit_offer_redemptions"),
    ("trg_phase10_revocation_no_truncate", "billing_staff_permission_revocations"),
    ("trg_phase10_grant_no_truncate", "billing_staff_permission_grants"),
    ("trg_phase10_offer_entitlement_event_guard", "entitlement_events"),
    ("trg_phase10_offer_grant_guard", "credit_ledger_entries"),
    ("trg_phase10_offer_lot_guard", "credit_lots"),
    ("trg_phase10_funding_immutable", "credit_offer_fundings"),
    ("trg_phase10_funding_guard", "credit_offer_fundings"),
    ("trg_phase10_redemption_immutable", "credit_offer_redemptions"),
    ("trg_phase10_redemption_final", "credit_offer_redemptions"),
    ("trg_phase10_redemption_guard", "credit_offer_redemptions"),
    ("trg_phase10_revocation_immutable", "billing_staff_permission_revocations"),
    ("trg_phase10_revocation_guard", "billing_staff_permission_revocations"),
    ("trg_phase10_grant_immutable", "billing_staff_permission_grants"),
)
PG_FUNCTIONS = (
    "phase10_offer_entitlement_event_guard()", "phase10_offer_grant_guard()", "phase10_offer_lot_guard()",
    "phase10_funding_guard()", "phase10_redemption_final()", "phase10_redemption_guard()",
    "phase10_revocation_guard()", "phase10_require_read_committed()",
    "phase10_reject_truncate()", "phase10_reject_row_change()",
)
SQLITE_TRIGGERS = tuple(
    f"trg_phase10_{table}_{action}" for table in TABLES for action in ("update", "delete")
) + ("trg_phase10_offer_lot_insert", "trg_phase10_offer_entitlement_event_insert")


def _sqlite_replace_gate(old_expression, new_expression):
    """Replace one CHECK expression on ``entitlement_instances`` in place.

    SQLite cannot ALTER a CHECK constraint. This follows SQLite's documented
    procedure for constraint changes that do not alter the on-disk format
    ("Making Other Kinds Of Table Schema Changes"): rewrite the stored table
    DDL under ``writable_schema`` and bump ``schema_version``. Rows, indexes,
    and triggers are untouched, so no data is copied and no foreign key is
    disturbed. Callers verify beforehand that existing rows satisfy the new
    expression; ``quick_check`` then confirms the schema still parses.
    """
    bind = op.get_bind()
    table_sql = bind.execute(sa.text(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='entitlement_instances'"
    )).scalar_one()
    if table_sql.count(old_expression) == 0 and table_sql.count(new_expression) == 1:
        return  # already in the target form (for example a model-created schema)
    if table_sql.count(old_expression) != 1:
        raise RuntimeError("entitlement_instances gate constraint is not in the expected form")
    rewritten = table_sql.replace(old_expression, new_expression)
    version = bind.execute(sa.text("PRAGMA schema_version")).scalar_one()
    bind.execute(sa.text("PRAGMA writable_schema=ON"))
    try:
        bind.execute(
            sa.text("UPDATE sqlite_master SET sql=:sql WHERE type='table' AND name='entitlement_instances'"),
            {"sql": rewritten},
        )
        bind.execute(sa.text(f"PRAGMA schema_version={int(version) + 1}"))
    finally:
        bind.execute(sa.text("PRAGMA writable_schema=OFF"))
    if bind.execute(sa.text("PRAGMA quick_check")).scalar_one() != "ok":
        raise RuntimeError("entitlement_instances schema check failed after the gate change")


def _sqlite_guards():
    _sqlite_replace_gate(OLD_GATE, NEW_GATE)
    for table in TABLES:
        for action in ("update", "delete"):
            op.execute(
                f"CREATE TRIGGER trg_phase10_{table}_{action} BEFORE {action.upper()} ON {table} "
                "BEGIN SELECT RAISE(ABORT,'Phase 10 offer and permission evidence is immutable'); END"
            )
    op.execute(
        "CREATE TRIGGER trg_phase10_offer_lot_insert BEFORE INSERT ON credit_lots "
        f"WHEN NEW.source_type IN ({OFFER_LOT_SOURCES}) AND NOT EXISTS ("
        "SELECT 1 FROM credit_offer_fundings f JOIN credit_offer_redemptions r ON r.id=f.redemption_id "
        "WHERE f.id=NEW.source_id AND f.lot_id=NEW.id AND f.billing_account_id=NEW.billing_account_id "
        "AND f.credit_amount=NEW.original_amount AND NEW.member_attribution_id IS NULL "
        "AND NEW.source_type = CASE r.origin WHEN 'trial' THEN 'trial' WHEN 'promotion' THEN 'promotional' "
        "WHEN 'comp' THEN 'comp' ELSE 'internal' END) "
        "BEGIN SELECT RAISE(ABORT,'trial, promotional, comp, and internal lots require Phase 10 offer funding evidence'); END"
    )
    op.execute(
        "CREATE TRIGGER trg_phase10_offer_entitlement_event_insert BEFORE INSERT ON entitlement_events "
        "WHEN NEW.from_state='proposed' AND NEW.to_state='scheduled' AND EXISTS (SELECT 1 FROM entitlement_instances i "
        f"WHERE i.id=NEW.entitlement_instance_id AND i.source_type IN ({OFFER_ENTITLEMENT_SOURCES})) "
        "AND NOT EXISTS (SELECT 1 FROM entitlement_instances i JOIN credit_offer_redemptions r "
        "ON r.id=i.source_id AND r.entitlement_instance_id=i.id "
        "AND r.entitlement_definition_id=i.entitlement_definition_id "
        "AND r.billing_account_id=i.billing_account_id AND r.origin=i.source_type "
        "WHERE i.id=NEW.entitlement_instance_id) "
        "BEGIN SELECT RAISE(ABORT,'trial, promotion, comp, and internal entitlements require Phase 10 redemption evidence'); END"
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
        op.execute(sa.text("LOCK TABLE entitlement_instances IN SHARE ROW EXCLUSIVE MODE"))
    for table in TABLES:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first() is not None:
            raise Phase10EvidenceNotEmptyError("Phase 10 downgrade refuses to discard offer and permission evidence")
    if bind.execute(sa.text(
        "SELECT 1 FROM entitlement_instances WHERE source_type IN ('trial','promotion','comp') "
        "AND state NOT IN ('proposed','cancelled') LIMIT 1"
    )).first() is not None:
        raise Phase10EvidenceNotEmptyError("Phase 10 downgrade refuses to re-gate activated offer entitlements")
    if bind.dialect.name == "postgresql":
        for trigger, table in PG_TRIGGERS:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger} ON {table}"))
        for function in PG_FUNCTIONS:
            op.execute(sa.text(f"DROP FUNCTION IF EXISTS {function}"))
        op.execute(f"ALTER TABLE entitlement_instances DROP CONSTRAINT {GATE_NAME}")
        op.execute(f"ALTER TABLE entitlement_instances ADD CONSTRAINT {GATE_NAME} CHECK ({OLD_GATE})")
    else:
        for trigger in SQLITE_TRIGGERS:
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))
    op.drop_index("ix_credit_offer_fundings_account", table_name="credit_offer_fundings")
    op.drop_index("ix_credit_offer_redemptions_permission", table_name="credit_offer_redemptions")
    op.drop_index("ix_credit_offer_redemptions_domain_event", table_name="credit_offer_redemptions")
    op.drop_index("ix_credit_offer_redemptions_account_redeemed", table_name="credit_offer_redemptions")
    op.drop_index("ix_billing_staff_permission_grants_user_permission", table_name="billing_staff_permission_grants")
    for table in TABLES:
        op.drop_table(table)
    if bind.dialect.name != "postgresql":
        _sqlite_replace_gate(NEW_GATE, OLD_GATE)
