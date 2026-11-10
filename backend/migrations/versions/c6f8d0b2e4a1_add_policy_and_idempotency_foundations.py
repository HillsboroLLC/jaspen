"""Add empty idempotency and pricing/capacity policy foundations.

Revision ID: c6f8d0b2e4a1
Revises: b5e7c9a1d3f2

Phase 2.2 is schema-only. It seeds no policies or rates and connects none of
the new tables to a runtime reader or writer.
"""

from alembic import op
import sqlalchemy as sa


revision = "c6f8d0b2e4a1"
down_revision = "b5e7c9a1d3f2"
branch_labels = None
depends_on = None


FOUNDATION_TABLES = (
    "idempotency_registry",
    "pricing_policy_versions",
    "provider_rate_entries",
    "capacity_policy_versions",
)


class PolicyFoundationNotEmptyError(RuntimeError):
    """Raised when downgrade would discard Phase 2.2 evidence."""


def _create_tables():
    op.create_table(
        "idempotency_registry",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("namespace", sa.String(64), nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("result_type", sa.String(64), nullable=True),
        sa.Column("result_id", sa.String(255), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(120), nullable=True),
        sa.CheckConstraint(
            "state IN ('claimed', 'completed', 'failed_retryable', 'failed_final')",
            name="ck_idempotency_registry_state",
        ),
        sa.CheckConstraint(
            "length(request_fingerprint) = 64 AND "
            "request_fingerprint = lower(request_fingerprint)",
            name="ck_idempotency_registry_fingerprint",
        ),
        sa.CheckConstraint(
            "((result_type IS NULL AND result_id IS NULL) OR "
            "(result_type IS NOT NULL AND result_id IS NOT NULL))",
            name="ck_idempotency_registry_result_reference",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR completed_at >= claimed_at",
            name="ck_idempotency_registry_completion_time",
        ),
        sa.CheckConstraint(
            "state != 'completed' OR completed_at IS NOT NULL",
            name="ck_idempotency_registry_completed_state",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR state = 'completed'",
            name="ck_idempotency_registry_completion_state",
        ),
        sa.CheckConstraint(
            "state = 'completed' OR (result_type IS NULL AND result_id IS NULL)",
            name="ck_idempotency_registry_result_state",
        ),
        sa.CheckConstraint(
            "state NOT IN ('failed_retryable', 'failed_final') OR "
            "last_error_code IS NOT NULL",
            name="ck_idempotency_registry_failure_error",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_idempotency_registry"),
        sa.UniqueConstraint(
            "namespace",
            "key",
            name="uq_idempotency_registry_namespace_key",
        ),
    )
    op.create_index(
        "ix_idempotency_registry_state_claimed_at",
        "idempotency_registry",
        ["state", "claimed_at"],
        unique=False,
    )
    op.create_index(
        "ix_idempotency_registry_result_reference",
        "idempotency_registry",
        ["result_type", "result_id"],
        unique=False,
        postgresql_where=sa.text("result_id IS NOT NULL"),
        sqlite_where=sa.text("result_id IS NOT NULL"),
    )

    op.create_table(
        "pricing_policy_versions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("announced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_user_id", sa.String(36), nullable=True),
        sa.Column("supersedes_id", sa.String(36), nullable=True),
        sa.Column("credit_conversion_version", sa.String(64), nullable=False),
        sa.Column("rounding_rule", sa.String(32), nullable=False),
        sa.Column("conversion_json", sa.JSON(), nullable=False),
        sa.Column("customer_credit_impact", sa.Boolean(), nullable=False),
        sa.Column("notice_required", sa.Boolean(), nullable=False),
        sa.Column("notice_evidence_reference", sa.String(255), nullable=True),
        sa.CheckConstraint(
            "state IN ('draft', 'approved', 'announced', 'effective', 'superseded')",
            name="ck_pricing_policy_versions_state",
        ),
        sa.CheckConstraint(
            "rounding_rule = 'ceil_whole_credit'",
            name="ck_pricing_policy_versions_rounding_rule",
        ),
        sa.CheckConstraint(
            "supersedes_id IS NULL OR supersedes_id != id",
            name="ck_pricing_policy_versions_not_self_superseding",
        ),
        sa.CheckConstraint(
            "state = 'draft' OR approved_at IS NOT NULL",
            name="ck_pricing_policy_versions_approval",
        ),
        sa.CheckConstraint(
            "state != 'announced' OR announced_at IS NOT NULL",
            name="ck_pricing_policy_versions_announcement",
        ),
        sa.CheckConstraint(
            "state NOT IN ('effective', 'superseded') OR effective_at IS NOT NULL",
            name="ck_pricing_policy_versions_effective_time",
        ),
        sa.CheckConstraint(
            "state != 'superseded' OR superseded_at IS NOT NULL",
            name="ck_pricing_policy_versions_superseded_time",
        ),
        sa.CheckConstraint(
            "superseded_at IS NULL OR state = 'superseded'",
            name="ck_pricing_policy_versions_superseded_state",
        ),
        sa.CheckConstraint(
            "announced_at IS NULL OR state IN ('announced', 'effective', 'superseded')",
            name="ck_pricing_policy_versions_announced_state",
        ),
        sa.CheckConstraint(
            "notice_evidence_reference IS NULL OR "
            "length(trim(notice_evidence_reference)) > 0",
            name="ck_pricing_policy_versions_notice_evidence_value",
        ),
        sa.CheckConstraint(
            "state NOT IN ('effective', 'superseded') OR NOT customer_credit_impact OR "
            "notice_required",
            name="ck_pricing_policy_versions_customer_impact_notice",
        ),
        sa.CheckConstraint(
            "state NOT IN ('effective', 'superseded') OR NOT notice_required OR "
            "(announced_at IS NOT NULL AND notice_evidence_reference IS NOT NULL "
            "AND announced_at < effective_at)",
            name="ck_pricing_policy_versions_notice_evidence",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"],
            ["users.id"],
            name="fk_pricing_policy_versions_approved_by_user_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["pricing_policy_versions.id"],
            name="fk_pricing_policy_versions_supersedes_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_pricing_policy_versions"),
        sa.UniqueConstraint("version", name="uq_pricing_policy_versions_version"),
    )
    op.create_index(
        "uq_pricing_policy_versions_single_effective",
        "pricing_policy_versions",
        ["state"],
        unique=True,
        postgresql_where=sa.text("state = 'effective'"),
        sqlite_where=sa.text("state = 'effective'"),
    )
    op.create_index(
        "ix_pricing_policy_versions_state_effective_at",
        "pricing_policy_versions",
        ["state", "effective_at"],
        unique=False,
    )
    op.create_index(
        "ix_pricing_policy_versions_approved_by_user_id",
        "pricing_policy_versions",
        ["approved_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_pricing_policy_versions_supersedes_id",
        "pricing_policy_versions",
        ["supersedes_id"],
        unique=False,
    )

    op.create_table(
        "provider_rate_entries",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("pricing_policy_version_id", sa.String(36), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("model", sa.String(255), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("unit_basis", sa.String(32), nullable=False),
        sa.Column("input_rate", sa.Numeric(20, 10), nullable=False),
        sa.Column("output_rate", sa.Numeric(20, 10), nullable=False),
        sa.Column("cache_tool_rate_json", sa.JSON(), nullable=True),
        sa.Column("source_reference", sa.String(255), nullable=False),
        sa.Column("source_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(provider)) > 0 AND length(trim(model)) > 0",
            name="ck_provider_rate_entries_identity",
        ),
        sa.CheckConstraint(
            "length(currency) = 3 AND currency = lower(currency) AND "
            "substr(currency, 1, 1) BETWEEN 'a' AND 'z' AND "
            "substr(currency, 2, 1) BETWEEN 'a' AND 'z' AND "
            "substr(currency, 3, 1) BETWEEN 'a' AND 'z'",
            name="ck_provider_rate_entries_currency",
        ),
        sa.CheckConstraint(
            "unit_basis = 'per_1m_tokens'",
            name="ck_provider_rate_entries_unit_basis",
        ),
        sa.CheckConstraint(
            "input_rate >= 0 AND output_rate >= 0",
            name="ck_provider_rate_entries_nonnegative_rates",
        ),
        sa.CheckConstraint(
            "length(trim(source_reference)) > 0",
            name="ck_provider_rate_entries_source_reference",
        ),
        sa.ForeignKeyConstraint(
            ["pricing_policy_version_id"],
            ["pricing_policy_versions.id"],
            name="fk_provider_rate_entries_pricing_policy_version_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_provider_rate_entries"),
        sa.UniqueConstraint(
            "pricing_policy_version_id",
            "provider",
            "model",
            name="uq_provider_rate_entries_policy_provider_model",
        ),
    )

    op.create_table(
        "capacity_policy_versions",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by_user_id", sa.String(36), nullable=True),
        sa.Column("approval_evidence_reference", sa.String(255), nullable=True),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("supersedes_id", sa.String(36), nullable=True),
        sa.Column("rules_json", sa.JSON(), nullable=False),
        sa.CheckConstraint(
            "state IN ('draft', 'approved', 'effective', 'superseded')",
            name="ck_capacity_policy_versions_state",
        ),
        sa.CheckConstraint(
            "supersedes_id IS NULL OR supersedes_id != id",
            name="ck_capacity_policy_versions_not_self_superseding",
        ),
        sa.CheckConstraint(
            "state = 'draft' OR "
            "(approved_at IS NOT NULL AND approval_evidence_reference IS NOT NULL)",
            name="ck_capacity_policy_versions_approval",
        ),
        sa.CheckConstraint(
            "state NOT IN ('effective', 'superseded') OR effective_at IS NOT NULL",
            name="ck_capacity_policy_versions_effective_time",
        ),
        sa.CheckConstraint(
            "state != 'superseded' OR superseded_at IS NOT NULL",
            name="ck_capacity_policy_versions_superseded_time",
        ),
        sa.CheckConstraint(
            "superseded_at IS NULL OR state = 'superseded'",
            name="ck_capacity_policy_versions_superseded_state",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"],
            ["users.id"],
            name="fk_capacity_policy_versions_approved_by_user_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["supersedes_id"],
            ["capacity_policy_versions.id"],
            name="fk_capacity_policy_versions_supersedes_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_capacity_policy_versions"),
        sa.UniqueConstraint("version", name="uq_capacity_policy_versions_version"),
    )
    op.create_index(
        "uq_capacity_policy_versions_single_effective",
        "capacity_policy_versions",
        ["state"],
        unique=True,
        postgresql_where=sa.text("state = 'effective'"),
        sqlite_where=sa.text("state = 'effective'"),
    )
    op.create_index(
        "ix_capacity_policy_versions_state_effective_at",
        "capacity_policy_versions",
        ["state", "effective_at"],
        unique=False,
    )
    op.create_index(
        "ix_capacity_policy_versions_approved_by_user_id",
        "capacity_policy_versions",
        ["approved_by_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_capacity_policy_versions_supersedes_id",
        "capacity_policy_versions",
        ["supersedes_id"],
        unique=False,
    )


def _create_postgresql_triggers():
    op.execute("""
        CREATE FUNCTION enforce_idempotency_registry_identity() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'INSERT' THEN
                IF NEW.request_fingerprint !~ '^[0-9a-f]{64}$' THEN
                    RAISE EXCEPTION 'request fingerprint must be lowercase SHA-256 hex'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'idempotency registry claims cannot be deleted'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.namespace IS DISTINCT FROM NEW.namespace
               OR OLD.key IS DISTINCT FROM NEW.key
               OR OLD.request_fingerprint IS DISTINCT FROM NEW.request_fingerprint
               OR OLD.claimed_at IS DISTINCT FROM NEW.claimed_at THEN
                RAISE EXCEPTION 'idempotency registry identity is immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF NOT (
                NEW.state = OLD.state
                OR (OLD.state = 'claimed' AND NEW.state IN (
                    'completed', 'failed_retryable', 'failed_final'
                ))
                OR (OLD.state = 'failed_retryable' AND NEW.state IN (
                    'claimed', 'failed_final'
                ))
            ) THEN
                RAISE EXCEPTION 'invalid idempotency lifecycle transition'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.state = 'completed' AND (
                OLD.completed_at IS DISTINCT FROM NEW.completed_at
                OR OLD.result_type IS DISTINCT FROM NEW.result_type
                OR OLD.result_id IS DISTINCT FROM NEW.result_id
            ) THEN
                RAISE EXCEPTION 'completed idempotency result is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_idempotency_registry_identity
        BEFORE INSERT OR UPDATE OR DELETE ON idempotency_registry
        FOR EACH ROW EXECUTE FUNCTION enforce_idempotency_registry_identity()
    """)

    op.execute("""
        CREATE FUNCTION enforce_pricing_policy_lifecycle() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.state <> 'draft' THEN
                    RAISE EXCEPTION 'approved pricing policies cannot be deleted'
                        USING ERRCODE = '23514';
                END IF;
                RETURN OLD;
            END IF;

            IF NOT (
                NEW.state = OLD.state
                OR (OLD.state = 'draft' AND NEW.state = 'approved')
                OR (OLD.state = 'approved' AND NEW.state = 'announced')
                OR (OLD.state = 'approved' AND NEW.state = 'effective'
                    AND NOT NEW.notice_required)
                OR (OLD.state = 'announced' AND NEW.state = 'effective')
                OR (OLD.state = 'effective' AND NEW.state = 'superseded')
            ) THEN
                RAISE EXCEPTION 'invalid pricing policy lifecycle transition'
                    USING ERRCODE = '23514';
            END IF;

            IF OLD.state <> 'draft' AND (
                OLD.version IS DISTINCT FROM NEW.version
                OR OLD.effective_at IS DISTINCT FROM NEW.effective_at
                OR OLD.approved_at IS DISTINCT FROM NEW.approved_at
                OR (OLD.approved_by_user_id IS DISTINCT FROM NEW.approved_by_user_id
                    AND NOT (OLD.approved_by_user_id IS NOT NULL
                             AND NEW.approved_by_user_id IS NULL))
                OR OLD.supersedes_id IS DISTINCT FROM NEW.supersedes_id
                OR OLD.credit_conversion_version IS DISTINCT FROM NEW.credit_conversion_version
                OR OLD.rounding_rule IS DISTINCT FROM NEW.rounding_rule
                OR OLD.conversion_json::text IS DISTINCT FROM NEW.conversion_json::text
                OR OLD.customer_credit_impact IS DISTINCT FROM NEW.customer_credit_impact
                OR OLD.notice_required IS DISTINCT FROM NEW.notice_required
                OR (OLD.notice_evidence_reference IS DISTINCT FROM NEW.notice_evidence_reference
                    AND NOT (
                        OLD.notice_evidence_reference IS NULL
                        AND NEW.notice_evidence_reference IS NOT NULL
                        AND OLD.state IN ('approved', 'announced')
                        AND NEW.state IN ('approved', 'announced')
                    ))
            ) THEN
                RAISE EXCEPTION 'approved pricing policy meaning is immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.state IN ('announced', 'effective', 'superseded')
               AND OLD.announced_at IS DISTINCT FROM NEW.announced_at THEN
                RAISE EXCEPTION 'pricing announcement evidence is immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.state = 'superseded'
               AND OLD.superseded_at IS DISTINCT FROM NEW.superseded_at THEN
                RAISE EXCEPTION 'pricing supersession evidence is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_pricing_policy_versions_lifecycle
        BEFORE UPDATE OR DELETE ON pricing_policy_versions
        FOR EACH ROW EXECUTE FUNCTION enforce_pricing_policy_lifecycle()
    """)

    op.execute("""
        CREATE FUNCTION enforce_provider_rate_immutability() RETURNS trigger AS $$
        DECLARE
            parent_state text;
        BEGIN
            IF TG_OP = 'DELETE' THEN
                SELECT state INTO parent_state FROM pricing_policy_versions
                WHERE id = OLD.pricing_policy_version_id;
                IF parent_state <> 'draft' THEN
                    RAISE EXCEPTION 'approved provider rates cannot be deleted'
                        USING ERRCODE = '23514';
                END IF;
                RETURN OLD;
            END IF;

            IF NEW.input_rate::text IN ('NaN', 'Infinity', '-Infinity')
               OR NEW.output_rate::text IN ('NaN', 'Infinity', '-Infinity') THEN
                RAISE EXCEPTION 'provider rates must be finite'
                    USING ERRCODE = '23514';
            END IF;

            SELECT state INTO parent_state FROM pricing_policy_versions
            WHERE id = NEW.pricing_policy_version_id;
            IF parent_state <> 'draft' THEN
                RAISE EXCEPTION 'provider rates may change only while policy is draft'
                    USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                SELECT state INTO parent_state FROM pricing_policy_versions
                WHERE id = OLD.pricing_policy_version_id;
                IF parent_state <> 'draft' THEN
                    RAISE EXCEPTION 'approved provider rates are immutable'
                        USING ERRCODE = '23514';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_provider_rate_entries_immutable
        BEFORE INSERT OR UPDATE OR DELETE ON provider_rate_entries
        FOR EACH ROW EXECUTE FUNCTION enforce_provider_rate_immutability()
    """)

    op.execute("""
        CREATE FUNCTION enforce_capacity_policy_lifecycle() RETURNS trigger AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.state <> 'draft' THEN
                    RAISE EXCEPTION 'approved capacity policies cannot be deleted'
                        USING ERRCODE = '23514';
                END IF;
                RETURN OLD;
            END IF;

            IF NOT (
                NEW.state = OLD.state
                OR (OLD.state = 'draft' AND NEW.state = 'approved')
                OR (OLD.state = 'approved' AND NEW.state = 'effective')
                OR (OLD.state = 'effective' AND NEW.state = 'superseded')
            ) THEN
                RAISE EXCEPTION 'invalid capacity policy lifecycle transition'
                    USING ERRCODE = '23514';
            END IF;

            IF OLD.state <> 'draft' AND (
                OLD.version IS DISTINCT FROM NEW.version
                OR OLD.effective_at IS DISTINCT FROM NEW.effective_at
                OR OLD.approved_at IS DISTINCT FROM NEW.approved_at
                OR (OLD.approved_by_user_id IS DISTINCT FROM NEW.approved_by_user_id
                    AND NOT (OLD.approved_by_user_id IS NOT NULL
                             AND NEW.approved_by_user_id IS NULL))
                OR OLD.approval_evidence_reference IS DISTINCT FROM NEW.approval_evidence_reference
                OR OLD.supersedes_id IS DISTINCT FROM NEW.supersedes_id
                OR OLD.rules_json::text IS DISTINCT FROM NEW.rules_json::text
            ) THEN
                RAISE EXCEPTION 'approved capacity policy meaning is immutable'
                    USING ERRCODE = '23514';
            END IF;
            IF OLD.state = 'superseded'
               AND OLD.superseded_at IS DISTINCT FROM NEW.superseded_at THEN
                RAISE EXCEPTION 'capacity supersession evidence is immutable'
                    USING ERRCODE = '23514';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_capacity_policy_versions_lifecycle
        BEFORE UPDATE OR DELETE ON capacity_policy_versions
        FOR EACH ROW EXECUTE FUNCTION enforce_capacity_policy_lifecycle()
    """)


def _create_sqlite_triggers():
    statements = (
        """
        CREATE TRIGGER trg_idempotency_registry_fingerprint_insert
        BEFORE INSERT ON idempotency_registry
        FOR EACH ROW WHEN
            length(NEW.request_fingerprint) != 64
            OR NEW.request_fingerprint GLOB '*[^0-9a-f]*'
        BEGIN
            SELECT RAISE(ABORT, 'request fingerprint must be lowercase SHA-256 hex');
        END
        """,
        """
        CREATE TRIGGER trg_idempotency_registry_fingerprint_update
        BEFORE UPDATE OF request_fingerprint ON idempotency_registry
        FOR EACH ROW WHEN
            length(NEW.request_fingerprint) != 64
            OR NEW.request_fingerprint GLOB '*[^0-9a-f]*'
        BEGIN
            SELECT RAISE(ABORT, 'request fingerprint must be lowercase SHA-256 hex');
        END
        """,
        """
        CREATE TRIGGER trg_idempotency_registry_identity_update
        BEFORE UPDATE ON idempotency_registry
        FOR EACH ROW WHEN
            OLD.namespace IS NOT NEW.namespace
            OR OLD.key IS NOT NEW.key
            OR OLD.request_fingerprint IS NOT NEW.request_fingerprint
            OR OLD.claimed_at IS NOT NEW.claimed_at
        BEGIN
            SELECT RAISE(ABORT, 'idempotency registry identity is immutable');
        END
        """,
        """
        CREATE TRIGGER trg_idempotency_registry_identity_delete
        BEFORE DELETE ON idempotency_registry
        BEGIN
            SELECT RAISE(ABORT, 'idempotency registry claims cannot be deleted');
        END
        """,
        """
        CREATE TRIGGER trg_idempotency_registry_lifecycle
        BEFORE UPDATE ON idempotency_registry
        FOR EACH ROW WHEN NOT (
            NEW.state = OLD.state
            OR (OLD.state = 'claimed' AND NEW.state IN (
                'completed', 'failed_retryable', 'failed_final'
            ))
            OR (OLD.state = 'failed_retryable' AND NEW.state IN (
                'claimed', 'failed_final'
            ))
        ) OR (
            OLD.state = 'completed' AND (
                OLD.completed_at IS NOT NEW.completed_at
                OR OLD.result_type IS NOT NEW.result_type
                OR OLD.result_id IS NOT NEW.result_id
            )
        )
        BEGIN
            SELECT RAISE(ABORT, 'invalid or immutable idempotency lifecycle');
        END
        """,
        """
        CREATE TRIGGER trg_pricing_policy_versions_transition
        BEFORE UPDATE ON pricing_policy_versions
        FOR EACH ROW WHEN NOT (
            NEW.state = OLD.state
            OR (OLD.state = 'draft' AND NEW.state = 'approved')
            OR (OLD.state = 'approved' AND NEW.state = 'announced')
            OR (OLD.state = 'approved' AND NEW.state = 'effective'
                AND NOT NEW.notice_required)
            OR (OLD.state = 'announced' AND NEW.state = 'effective')
            OR (OLD.state = 'effective' AND NEW.state = 'superseded')
        )
        BEGIN
            SELECT RAISE(ABORT, 'invalid pricing policy lifecycle transition');
        END
        """,
        """
        CREATE TRIGGER trg_pricing_policy_versions_immutable
        BEFORE UPDATE ON pricing_policy_versions
        FOR EACH ROW WHEN OLD.state <> 'draft' AND (
            OLD.version IS NOT NEW.version
            OR OLD.effective_at IS NOT NEW.effective_at
            OR OLD.approved_at IS NOT NEW.approved_at
            OR (OLD.approved_by_user_id IS NOT NEW.approved_by_user_id
                AND NOT (OLD.approved_by_user_id IS NOT NULL
                         AND NEW.approved_by_user_id IS NULL))
            OR OLD.supersedes_id IS NOT NEW.supersedes_id
            OR OLD.credit_conversion_version IS NOT NEW.credit_conversion_version
            OR OLD.rounding_rule IS NOT NEW.rounding_rule
            OR OLD.conversion_json IS NOT NEW.conversion_json
            OR OLD.customer_credit_impact IS NOT NEW.customer_credit_impact
            OR OLD.notice_required IS NOT NEW.notice_required
            OR (OLD.notice_evidence_reference IS NOT NEW.notice_evidence_reference
                AND NOT (
                    OLD.notice_evidence_reference IS NULL
                    AND NEW.notice_evidence_reference IS NOT NULL
                    AND OLD.state IN ('approved', 'announced')
                    AND NEW.state IN ('approved', 'announced')
                ))
            OR (OLD.state IN ('announced', 'effective', 'superseded')
                AND OLD.announced_at IS NOT NEW.announced_at)
            OR (OLD.state = 'superseded'
                AND OLD.superseded_at IS NOT NEW.superseded_at)
        )
        BEGIN
            SELECT RAISE(ABORT, 'approved pricing policy meaning is immutable');
        END
        """,
        """
        CREATE TRIGGER trg_pricing_policy_versions_delete
        BEFORE DELETE ON pricing_policy_versions
        FOR EACH ROW WHEN OLD.state <> 'draft'
        BEGIN
            SELECT RAISE(ABORT, 'approved pricing policies cannot be deleted');
        END
        """,
        """
        CREATE TRIGGER trg_provider_rate_entries_finite_insert
        BEFORE INSERT ON provider_rate_entries
        FOR EACH ROW WHEN
            NEW.input_rate IS NULL OR NEW.output_rate IS NULL
            OR NOT (
                NEW.input_rate >= 0 AND NEW.input_rate < 1e999
                AND NEW.output_rate >= 0 AND NEW.output_rate < 1e999
            )
        BEGIN
            SELECT RAISE(ABORT, 'provider rates must be finite and nonnegative');
        END
        """,
        """
        CREATE TRIGGER trg_provider_rate_entries_finite_update
        BEFORE UPDATE OF input_rate, output_rate ON provider_rate_entries
        FOR EACH ROW WHEN
            NEW.input_rate IS NULL OR NEW.output_rate IS NULL
            OR NOT (
                NEW.input_rate >= 0 AND NEW.input_rate < 1e999
                AND NEW.output_rate >= 0 AND NEW.output_rate < 1e999
            )
        BEGIN
            SELECT RAISE(ABORT, 'provider rates must be finite and nonnegative');
        END
        """,
        """
        CREATE TRIGGER trg_provider_rate_entries_insert
        BEFORE INSERT ON provider_rate_entries
        FOR EACH ROW WHEN (
            SELECT state FROM pricing_policy_versions
            WHERE id = NEW.pricing_policy_version_id
        ) <> 'draft'
        BEGIN
            SELECT RAISE(ABORT, 'provider rates may change only while policy is draft');
        END
        """,
        """
        CREATE TRIGGER trg_provider_rate_entries_update
        BEFORE UPDATE ON provider_rate_entries
        FOR EACH ROW WHEN
            (SELECT state FROM pricing_policy_versions
             WHERE id = OLD.pricing_policy_version_id) <> 'draft'
            OR (SELECT state FROM pricing_policy_versions
                WHERE id = NEW.pricing_policy_version_id) <> 'draft'
        BEGIN
            SELECT RAISE(ABORT, 'approved provider rates are immutable');
        END
        """,
        """
        CREATE TRIGGER trg_provider_rate_entries_delete
        BEFORE DELETE ON provider_rate_entries
        FOR EACH ROW WHEN (
            SELECT state FROM pricing_policy_versions
            WHERE id = OLD.pricing_policy_version_id
        ) <> 'draft'
        BEGIN
            SELECT RAISE(ABORT, 'approved provider rates cannot be deleted');
        END
        """,
        """
        CREATE TRIGGER trg_capacity_policy_versions_transition
        BEFORE UPDATE ON capacity_policy_versions
        FOR EACH ROW WHEN NOT (
            NEW.state = OLD.state
            OR (OLD.state = 'draft' AND NEW.state = 'approved')
            OR (OLD.state = 'approved' AND NEW.state = 'effective')
            OR (OLD.state = 'effective' AND NEW.state = 'superseded')
        )
        BEGIN
            SELECT RAISE(ABORT, 'invalid capacity policy lifecycle transition');
        END
        """,
        """
        CREATE TRIGGER trg_capacity_policy_versions_immutable
        BEFORE UPDATE ON capacity_policy_versions
        FOR EACH ROW WHEN OLD.state <> 'draft' AND (
            OLD.version IS NOT NEW.version
            OR OLD.effective_at IS NOT NEW.effective_at
            OR OLD.approved_at IS NOT NEW.approved_at
            OR (OLD.approved_by_user_id IS NOT NEW.approved_by_user_id
                AND NOT (OLD.approved_by_user_id IS NOT NULL
                         AND NEW.approved_by_user_id IS NULL))
            OR OLD.approval_evidence_reference IS NOT NEW.approval_evidence_reference
            OR OLD.supersedes_id IS NOT NEW.supersedes_id
            OR OLD.rules_json IS NOT NEW.rules_json
            OR (OLD.state = 'superseded'
                AND OLD.superseded_at IS NOT NEW.superseded_at)
        )
        BEGIN
            SELECT RAISE(ABORT, 'approved capacity policy meaning is immutable');
        END
        """,
        """
        CREATE TRIGGER trg_capacity_policy_versions_delete
        BEFORE DELETE ON capacity_policy_versions
        FOR EACH ROW WHEN OLD.state <> 'draft'
        BEGIN
            SELECT RAISE(ABORT, 'approved capacity policies cannot be deleted');
        END
        """,
    )
    for statement in statements:
        op.execute(statement)


def upgrade():
    _create_tables()
    dialect = op.get_bind().dialect.name
    if dialect == "postgresql":
        _create_postgresql_triggers()
    elif dialect == "sqlite":
        _create_sqlite_triggers()
    else:
        raise RuntimeError(f"Phase 2.2 migration does not support dialect {dialect!r}")


def _drop_triggers(dialect):
    if dialect == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_capacity_policy_versions_lifecycle ON capacity_policy_versions")
        op.execute("DROP TRIGGER IF EXISTS trg_provider_rate_entries_immutable ON provider_rate_entries")
        op.execute("DROP TRIGGER IF EXISTS trg_pricing_policy_versions_lifecycle ON pricing_policy_versions")
        op.execute("DROP TRIGGER IF EXISTS trg_idempotency_registry_identity ON idempotency_registry")
        op.execute("DROP FUNCTION IF EXISTS enforce_capacity_policy_lifecycle()")
        op.execute("DROP FUNCTION IF EXISTS enforce_provider_rate_immutability()")
        op.execute("DROP FUNCTION IF EXISTS enforce_pricing_policy_lifecycle()")
        op.execute("DROP FUNCTION IF EXISTS enforce_idempotency_registry_identity()")
    elif dialect == "sqlite":
        for trigger in (
            "trg_capacity_policy_versions_delete",
            "trg_capacity_policy_versions_immutable",
            "trg_capacity_policy_versions_transition",
            "trg_provider_rate_entries_delete",
            "trg_provider_rate_entries_update",
            "trg_provider_rate_entries_insert",
            "trg_provider_rate_entries_finite_update",
            "trg_provider_rate_entries_finite_insert",
            "trg_pricing_policy_versions_delete",
            "trg_pricing_policy_versions_immutable",
            "trg_pricing_policy_versions_transition",
            "trg_idempotency_registry_identity_delete",
            "trg_idempotency_registry_identity_update",
            "trg_idempotency_registry_lifecycle",
            "trg_idempotency_registry_fingerprint_update",
            "trg_idempotency_registry_fingerprint_insert",
        ):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS {trigger}"))


def downgrade():
    """Drop the Phase 2.2 foundation only while every table is empty."""
    bind = op.get_bind()
    counts = {
        table: bind.execute(sa.text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
        for table in FOUNDATION_TABLES
    }
    if any(counts.values()):
        details = ", ".join(f"{table}={count}" for table, count in counts.items())
        raise PolicyFoundationNotEmptyError(
            f"Cannot downgrade {revision}: {details}. Phase 2.2 downgrade may "
            "remove only empty foundation tables."
        )

    dialect = bind.dialect.name
    _drop_triggers(dialect)

    op.drop_index(
        "ix_capacity_policy_versions_supersedes_id",
        table_name="capacity_policy_versions",
    )
    op.drop_index(
        "ix_capacity_policy_versions_approved_by_user_id",
        table_name="capacity_policy_versions",
    )
    op.drop_index(
        "ix_capacity_policy_versions_state_effective_at",
        table_name="capacity_policy_versions",
    )
    op.drop_index(
        "uq_capacity_policy_versions_single_effective",
        table_name="capacity_policy_versions",
    )
    op.drop_table("capacity_policy_versions")

    op.drop_table("provider_rate_entries")

    op.drop_index(
        "ix_pricing_policy_versions_supersedes_id",
        table_name="pricing_policy_versions",
    )
    op.drop_index(
        "ix_pricing_policy_versions_approved_by_user_id",
        table_name="pricing_policy_versions",
    )
    op.drop_index(
        "ix_pricing_policy_versions_state_effective_at",
        table_name="pricing_policy_versions",
    )
    op.drop_index(
        "uq_pricing_policy_versions_single_effective",
        table_name="pricing_policy_versions",
    )
    op.drop_table("pricing_policy_versions")

    op.drop_index(
        "ix_idempotency_registry_result_reference",
        table_name="idempotency_registry",
    )
    op.drop_index(
        "ix_idempotency_registry_state_claimed_at",
        table_name="idempotency_registry",
    )
    op.drop_table("idempotency_registry")
