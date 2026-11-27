"""Phase 17 reliable-delivery activation gate (inactive integration)."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta, timezone
import os
from pathlib import Path
import threading
from unittest import mock

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from app.ai_audit import persist_operation
from app.billing_reliable_delivery import (
    ReliableDeliveryConflictError,
    ReliableDeliveryTimingError,
    append_provider_attempt,
    assert_delivery_timing,
    persist_successful_response,
    provider_cost_reconciliation,
    recover_persisted_response,
    recover_reliable_deliveries,
    settle_persisted_response,
)
from app.billing_ai_operations import AIBillingIsolationError, release_without_billable_usage
from app.models import AIOperation, AIProviderAttempt, CreditLedgerEntry, CreditReservation, User
from app.models_billing_phase12 import AIBillingOperation, AIProviderCallUsage
from tests.test_billing_ai_operations import (
    _migrated_engine,
    _pg_world,
    authorize,
    call,
    charged,
    db_now,
    migrated_session,
    operation,
    sums,
    world,
)


MIGRATIONS_DIR = str(Path(__file__).resolve().parents[1] / "migrations")
REVISION = "f3a5c7e9b1d2"
PG = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="local disposable PostgreSQL is not configured")


def migration_module():
    return ScriptDirectory(MIGRATIONS_DIR).get_revision(REVISION).module


def legacy_attempt(session, operation_id, *, duration_ms=10):
    attempt = AIProviderAttempt(
        operation_id=operation_id,
        sequence=1,
        provider="anthropic",
        model="legacy-test",
        outcome="failed",
        duration_ms=duration_ms,
        input_tokens=0,
        output_tokens=0,
        customer_billable=False,
        metadata_json={},
    )
    session.add(attempt)
    session.flush()
    return attempt


def test_phase17_migration_extends_phase14_and_bi1_is_the_single_head():
    script = ScriptDirectory(MIGRATIONS_DIR)
    assert script.get_heads() == ["d7e9b1c3a5f8"]  # I3 follows I2; I2 follows I1; I1 follows BI-1; BI-1 extends this guard
    assert script.get_revision("c8a9989843b5").down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == "d2f4a6c8e0b3"


def prepared(session, *, label="reported", response=None):
    ns = world(session)
    authorization = authorize(session, ns)
    call(session, authorization.operation_id, label=label)
    provider_call = session.execute(sa.select(AIProviderCallUsage).where(
        AIProviderCallUsage.operation_id == authorization.operation_id,
    )).scalar_one()
    attempt, replay = append_provider_attempt(
        session,
        operation_id=authorization.operation_id,
        organization_id=ns.org,
        actor_user_id=ns.owner,
        provider_call_usage_id=provider_call.id,
        duration_ms=120,
        status_code=200,
        operational_metadata={"worker": "phase17-test"},
    )
    assert not replay
    envelope, replay = persist_successful_response(
        session,
        operation_id=authorization.operation_id,
        organization_id=ns.org,
        actor_user_id=ns.owner,
        delivered_attempt_number=1,
        response_json=response or {"message": "durably saved"},
    )
    assert not replay
    return ns, authorization, provider_call, attempt, envelope


def test_response_is_recoverable_before_settlement_and_settles_once(db):
    session = db.session
    ns, authorization, _call, _attempt, envelope = prepared(session)

    assert envelope["settlement"] is None
    assert recover_persisted_response(
        session,
        operation_id=authorization.operation_id,
        organization_id=ns.org,
        actor_user_id=ns.owner,
    ) == {"message": "durably saved"}
    assert charged(session, authorization.operation_id) == 0

    first = settle_persisted_response(
        session,
        operation_id=authorization.operation_id,
        organization_id=ns.org,
        actor_user_id=ns.owner,
    )
    second = settle_persisted_response(
        session,
        operation_id=authorization.operation_id,
        organization_id=ns.org,
        actor_user_id=ns.owner,
    )
    assert first.charged_credits == second.charged_credits == 18
    assert second.replay
    assert charged(session, authorization.operation_id) == 18
    assert provider_cost_reconciliation(session, operation_id=authorization.operation_id)["reconciled"]


def test_recovery_sweep_settles_saved_responses_before_expiring_other_lapsed_leases(db, monkeypatch):
    session = db.session
    ns, saved, _call, _attempt, _envelope = prepared(session)
    unanswered = authorize(session, ns)
    expires = session.get(AIBillingOperation, saved.operation_id).authorized_at + timedelta(seconds=1)
    for operation_id in (saved.operation_id, unanswered.operation_id):
        billing = session.get(AIBillingOperation, operation_id)
        reservation = session.execute(sa.select(CreditReservation).where(
            CreditReservation.operation_id == operation_id,
        )).scalar_one()
        billing.expires_at = expires
        reservation.expires_at = expires
    session.flush()
    after_lapse = expires.replace(tzinfo=expires.tzinfo or timezone.utc) + timedelta(seconds=1)
    monkeypatch.setattr("app.billing_ai_operations._clock", lambda _session: after_lapse)
    monkeypatch.setattr("app.billing_reliable_delivery._clock", lambda _session: after_lapse)

    report = recover_reliable_deliveries(session)
    assert [row["operation_id"] for row in report["settled"]] == [saved.operation_id]
    assert [row["operation_id"] for row in report["expired"]] == [unanswered.operation_id]
    assert session.get(AIBillingOperation, saved.operation_id).delivery_status == "delivered"
    assert session.get(AIBillingOperation, saved.operation_id).charged_credits == 0
    assert session.get(AIBillingOperation, unanswered.operation_id).delivery_status == "unsettled"
    assert sums(session, ns.account)[1] == 0


def test_recovery_sweep_pages_past_historical_and_unsaved_rows(db):
    session = db.session
    ns = world(
        session,
        credits=100_000,
        member={"max_concurrent": 500, "max_operations": 500},
        organization={"max_concurrent": 500, "max_operations": 500},
    )
    for index in range(101):
        historical = authorize(session, ns, step=f"historical-{index}")
        release_without_billable_usage(session, operation_id=historical.operation_id)
    for index in range(101):
        authorize(session, ns, step=f"inflight-{index}")

    saved = authorize(session, ns, step="saved-behind-backlog")
    call(session, saved.operation_id)
    provider_call = session.execute(sa.select(AIProviderCallUsage).where(
        AIProviderCallUsage.operation_id == saved.operation_id,
    )).scalar_one()
    append_provider_attempt(
        session,
        operation_id=saved.operation_id,
        organization_id=ns.org,
        actor_user_id=ns.owner,
        provider_call_usage_id=provider_call.id,
    )
    persist_successful_response(
        session,
        operation_id=saved.operation_id,
        organization_id=ns.org,
        actor_user_id=ns.owner,
        delivered_attempt_number=1,
        response_json={"message": "saved after more than one page"},
    )

    report = recover_reliable_deliveries(session, limit=1)
    assert [row["operation_id"] for row in report["settled"]] == [saved.operation_id]
    assert report["blocked"] == []
    assert session.get(AIBillingOperation, saved.operation_id).delivery_status == "delivered"


def test_recovery_sweep_isolates_malformed_identity_and_continues(db, monkeypatch):
    session = db.session
    _bad_ns, bad, _call, _attempt, _envelope = prepared(session)
    good_ns, good, _call, _attempt, _envelope = prepared(session)
    unanswered = authorize(session, good_ns)
    session.get(AIOperation, bad.operation_id).user_id = good_ns.owner

    billing = session.get(AIBillingOperation, unanswered.operation_id)
    reservation = session.execute(sa.select(CreditReservation).where(
        CreditReservation.operation_id == unanswered.operation_id,
    )).scalar_one()
    expires = billing.authorized_at + timedelta(seconds=1)
    billing.expires_at = expires
    reservation.expires_at = expires
    session.flush()
    after_lapse = expires.replace(tzinfo=expires.tzinfo or timezone.utc) + timedelta(seconds=1)
    monkeypatch.setattr("app.billing_ai_operations._clock", lambda _session: after_lapse)
    monkeypatch.setattr("app.billing_reliable_delivery._clock", lambda _session: after_lapse)

    first = recover_reliable_deliveries(session)
    assert [row["operation_id"] for row in first["blocked"]] == [bad.operation_id]
    assert [row["operation_id"] for row in first["settled"]] == [good.operation_id]
    assert [row["operation_id"] for row in first["expired"]] == [unanswered.operation_id]
    assert charged(session, good.operation_id) == 18

    second = recover_reliable_deliveries(session)
    assert [row["operation_id"] for row in second["blocked"]] == [bad.operation_id]
    assert second["settled"] == [] and second["expired"] == []
    assert charged(session, good.operation_id) == 18


def test_unknown_or_estimated_usage_is_never_charged_and_reconciles_as_absorbed(db):
    session = db.session
    ns, authorization, _call, _attempt, _envelope = prepared(session, label="estimated")
    result = settle_persisted_response(
        session,
        operation_id=authorization.operation_id,
        organization_id=ns.org,
        actor_user_id=ns.owner,
    )
    proof = provider_cost_reconciliation(session, operation_id=authorization.operation_id)
    assert result.charged_credits == 0
    assert not proof["uncertain_usage_charged"] and proof["reconciled"]
    assert not session.execute(sa.select(CreditLedgerEntry).where(
        CreditLedgerEntry.operation_id == authorization.operation_id,
        CreditLedgerEntry.entry_type == "settlement",
    )).first()


def test_every_delivery_path_enforces_durable_organization_and_member_identity(db):
    session = db.session
    ns, authorization, _call, _attempt, _envelope = prepared(session)
    other = world(session)
    with pytest.raises(AIBillingIsolationError, match="another organization or member"):
        recover_persisted_response(
            session,
            operation_id=authorization.operation_id,
            organization_id=other.org,
            actor_user_id=ns.owner,
        )
    with pytest.raises(AIBillingIsolationError, match="another organization or member"):
        settle_persisted_response(
            session,
            operation_id=authorization.operation_id,
            organization_id=ns.org,
            actor_user_id=other.owner,
        )


def test_persisted_response_is_immutable_and_integrity_checked(db):
    session = db.session
    ns, authorization, _call, _attempt, _envelope = prepared(session)
    same, replay = persist_successful_response(
        session,
        operation_id=authorization.operation_id,
        organization_id=ns.org,
        actor_user_id=ns.owner,
        delivered_attempt_number=1,
        response_json={"message": "durably saved"},
    )
    assert replay and same["response_sha256"]
    with pytest.raises(ReliableDeliveryConflictError, match="cannot be replaced"):
        persist_successful_response(
            session,
            operation_id=authorization.operation_id,
            organization_id=ns.org,
            actor_user_id=ns.owner,
            delivered_attempt_number=1,
            response_json={"message": "different"},
        )


def test_phase12_operational_attempts_are_append_only_and_linked_to_call_evidence(db):
    session = db.session
    ns, authorization, provider_call, attempt, _envelope = prepared(session)
    replayed, replay = append_provider_attempt(
        session,
        operation_id=authorization.operation_id,
        organization_id=ns.org,
        actor_user_id=ns.owner,
        provider_call_usage_id=provider_call.id,
        duration_ms=120,
        status_code=200,
        operational_metadata={"worker": "phase17-test"},
    )
    assert replay and replayed.id == attempt.id
    assert replayed.metadata_json["phase12_call_usage_id"] == provider_call.id

    user = session.get(User, ns.owner)
    with pytest.raises(RuntimeError, match="append-only"):
        persist_operation(
            user,
            usage={"operation_id": authorization.operation_id, "provider": "anthropic", "model": "claude-test"},
            charged_credits=0,
        )
    assert session.execute(sa.select(sa.func.count()).select_from(AIProviderAttempt).where(
        AIProviderAttempt.operation_id == authorization.operation_id,
    )).scalar_one() == 1


def test_delivery_timing_requires_lease_longer_than_timeout_plus_heartbeat(db):
    session = db.session
    ns = world(session)
    authorization = authorize(session, ns)
    assert assert_delivery_timing(
        session,
        operation_id=authorization.operation_id,
        provider_timeout_seconds=60,
        heartbeat_interval_seconds=30,
    )["lease_seconds"] == 120
    with pytest.raises(ReliableDeliveryTimingError, match="must exceed"):
        assert_delivery_timing(
            session,
            operation_id=authorization.operation_id,
            provider_timeout_seconds=90,
            heartbeat_interval_seconds=30,
        )


def test_unbound_legacy_operation_keeps_legacy_attempt_behavior(db):
    session = db.session
    ns = world(session)
    operation_id = operation(session, ns)
    user = session.get(User, ns.owner)
    persist_operation(
        user,
        usage={"operation_id": operation_id, "provider": "anthropic", "model": "claude-test"},
        charged_credits=0,
        success=False,
    )
    session.flush()
    assert session.get(AIOperation, operation_id) is not None
    assert session.get(AIBillingOperation, operation_id) is None


def test_sqlite_migration_guards_bound_attempts_and_refuses_unsafe_downgrade(db):
    session = db.session
    ns, authorization, _provider_call, attempt, _envelope = prepared(session)
    session.flush()
    context = MigrationContext.configure(session.connection())
    operations = Operations(context)
    module = migration_module()
    with mock.patch.object(module, "op", operations):
        module.upgrade()
        unbound = legacy_attempt(session, operation(session, ns))
        session.execute(sa.update(AIProviderAttempt).where(
            AIProviderAttempt.id == unbound.id,
        ).values(duration_ms=321))
        session.flush()
        session.refresh(unbound)
        assert unbound.duration_ms == 321
        savepoint = session.begin_nested()
        try:
            with pytest.raises(sa.exc.IntegrityError, match="append-only"):
                session.execute(sa.update(AIProviderAttempt).where(
                    AIProviderAttempt.id == unbound.id,
                ).values(operation_id=authorization.operation_id))
        finally:
            savepoint.rollback()
        savepoint = session.begin_nested()
        try:
            with pytest.raises(sa.exc.IntegrityError, match="append-only"):
                session.execute(sa.update(AIProviderAttempt).where(
                    AIProviderAttempt.id == attempt.id,
                ).values(duration_ms=999))
        finally:
            savepoint.rollback()
        savepoint = session.begin_nested()
        try:
            with pytest.raises(sa.exc.IntegrityError, match="append-only"):
                session.execute(sa.delete(AIProviderAttempt).where(AIProviderAttempt.id == attempt.id))
        finally:
            savepoint.rollback()
        with pytest.raises(module.Phase17EvidenceNotEmptyError, match="cannot remove"):
            module.downgrade()
    assert session.get(AIOperation, authorization.operation_id) is not None


@PG
def test_postgres_migration_allows_unbound_updates_but_guards_bound_rows():
    engine = _migrated_engine()
    try:
        ns = _pg_world(engine)
        with migrated_session(engine) as session:
            authorization = authorize(session, ns)
            bound = legacy_attempt(session, authorization.operation_id)
            unbound = legacy_attempt(session, operation(session, ns))
            session.commit()

            session.execute(sa.update(AIProviderAttempt).where(
                AIProviderAttempt.id == unbound.id,
            ).values(duration_ms=654))
            session.commit()
            assert session.get(AIProviderAttempt, unbound.id).duration_ms == 654

            for statement in (
                sa.update(AIProviderAttempt).where(
                    AIProviderAttempt.id == unbound.id,
                ).values(operation_id=authorization.operation_id),
                sa.update(AIProviderAttempt).where(
                    AIProviderAttempt.id == bound.id,
                ).values(duration_ms=999),
                sa.delete(AIProviderAttempt).where(AIProviderAttempt.id == bound.id),
            ):
                with pytest.raises(sa.exc.IntegrityError, match="append-only"):
                    session.execute(statement)
                session.rollback()
    finally:
        engine.dispose()


@PG
def test_postgres_recovery_workers_converge_to_one_charge_and_one_saved_response():
    engine = _migrated_engine()
    try:
        ns = _pg_world(engine)
        with migrated_session(engine) as session:
            authorization = authorize(session, ns)
            call(session, authorization.operation_id)
            provider_call = session.execute(sa.select(AIProviderCallUsage).where(
                AIProviderCallUsage.operation_id == authorization.operation_id,
            )).scalar_one()
            append_provider_attempt(
                session,
                operation_id=authorization.operation_id,
                organization_id=ns.org,
                actor_user_id=ns.owner,
                provider_call_usage_id=provider_call.id,
            )
            persist_successful_response(
                session,
                operation_id=authorization.operation_id,
                organization_id=ns.org,
                actor_user_id=ns.owner,
                delivered_attempt_number=1,
                response_json={"message": "saved before concurrent settlement"},
            )
            session.commit()

        barrier = threading.Barrier(4)

        def run(_index):
            with migrated_session(engine) as session:
                barrier.wait()
                result = settle_persisted_response(
                    session,
                    operation_id=authorization.operation_id,
                    organization_id=ns.org,
                    actor_user_id=ns.owner,
                )
                session.commit()
                return result.replay

        with ThreadPoolExecutor(4) as pool:
            replays = list(pool.map(run, range(4)))
        assert sorted(replays) == [False, True, True, True]
        with migrated_session(engine) as session:
            assert charged(session, authorization.operation_id) == 18
            assert recover_persisted_response(
                session,
                operation_id=authorization.operation_id,
                organization_id=ns.org,
                actor_user_id=ns.owner,
            ) == {"message": "saved before concurrent settlement"}
    finally:
        engine.dispose()
