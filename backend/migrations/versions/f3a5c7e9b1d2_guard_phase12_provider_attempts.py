"""Phase 17: make operational attempts append-only once Phase 12 binds them.

The legacy audit helper replaces ``ai_provider_attempts`` on replay.  Phase 17
must preserve those operational rows because Phase 12 financial call evidence
links to them by operation and provider request identity.  This additive guard
leaves unbound legacy operations unchanged and creates no live caller, worker,
route, pricing, policy, or billing activation.

Revision ID: f3a5c7e9b1d2
Revises: d2f4a6c8e0b3
"""

from alembic import op
import sqlalchemy as sa


revision = "f3a5c7e9b1d2"
down_revision = "d2f4a6c8e0b3"
branch_labels = None
depends_on = None


class Phase17EvidenceNotEmptyError(RuntimeError):
    """Downgrade refuses to make bound operational evidence mutable again."""


def _postgres_upgrade():
    op.execute(sa.text("""
        CREATE OR REPLACE FUNCTION phase17_guard_bound_provider_attempt_mutation()
        RETURNS trigger AS $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM ai_billing_operations
                WHERE operation_id = OLD.operation_id
            ) OR (
                TG_OP = 'UPDATE' AND EXISTS (
                    SELECT 1 FROM ai_billing_operations
                    WHERE operation_id = NEW.operation_id
                )
            ) THEN
                RAISE EXCEPTION 'Phase 12-bound provider attempts are append-only'
                    USING ERRCODE = '23514';
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
    """))
    for action in ("UPDATE", "DELETE"):
        op.execute(sa.text(f"""
            CREATE TRIGGER trg_phase17_bound_provider_attempt_{action.lower()}
            BEFORE {action} ON ai_provider_attempts
            FOR EACH ROW EXECUTE FUNCTION phase17_guard_bound_provider_attempt_mutation()
        """))


def _sqlite_upgrade():
    op.execute(sa.text("""
        CREATE TRIGGER trg_phase17_bound_provider_attempt_update
        BEFORE UPDATE ON ai_provider_attempts
        FOR EACH ROW
        WHEN EXISTS (
            SELECT 1 FROM ai_billing_operations
            WHERE operation_id = OLD.operation_id
        ) OR EXISTS (
            SELECT 1 FROM ai_billing_operations
            WHERE operation_id = NEW.operation_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'Phase 12-bound provider attempts are append-only');
        END
    """))
    op.execute(sa.text("""
        CREATE TRIGGER trg_phase17_bound_provider_attempt_delete
        BEFORE DELETE ON ai_provider_attempts
        FOR EACH ROW
        WHEN EXISTS (
                SELECT 1 FROM ai_billing_operations
                WHERE operation_id = OLD.operation_id
        )
        BEGIN
            SELECT RAISE(ABORT, 'Phase 12-bound provider attempts are append-only');
        END
    """))


def upgrade():
    if op.get_bind().dialect.name == "postgresql":
        _postgres_upgrade()
    else:
        _sqlite_upgrade()


def downgrade():
    bind = op.get_bind()
    bound = bind.execute(sa.text("""
        SELECT 1
        FROM ai_provider_attempts attempt
        JOIN ai_billing_operations billing ON billing.operation_id = attempt.operation_id
        LIMIT 1
    """)).first()
    if bound is not None:
        raise Phase17EvidenceNotEmptyError(
            "cannot remove the append-only guard while Phase 12-bound provider attempts exist"
        )
    if bind.dialect.name == "postgresql":
        for action in ("update", "delete"):
            op.execute(sa.text(
                f"DROP TRIGGER IF EXISTS trg_phase17_bound_provider_attempt_{action} ON ai_provider_attempts"
            ))
        op.execute(sa.text("DROP FUNCTION IF EXISTS phase17_guard_bound_provider_attempt_mutation()"))
    else:
        for action in ("update", "delete"):
            op.execute(sa.text(f"DROP TRIGGER IF EXISTS trg_phase17_bound_provider_attempt_{action}"))
