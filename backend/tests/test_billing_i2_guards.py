"""I2 database guards on a fully migrated PostgreSQL: the D5 allocation basis and Phase 9 F4 reconciliation."""

import os

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app import billing_financial_cases as cases
from app import billing_financial_effects as effects
from tests.test_billing_financial_effects import (
    _migrated_engine,
    dispute,
    monthly_subscription_lot,
    pack_purchase,
    seed_account,
)

PG = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="local disposable PostgreSQL is not configured")
HEAD = "e7b9d1f3a5c6"


def _engine():
    engine = _migrated_engine()
    with engine.connect() as connection:
        if connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one() != HEAD:
            engine.dispose()
            pytest.fail(f"I2 guard tests require Alembic head {HEAD}")
    return engine


def test_the_basis_rule_classifies_recorded_evidence(db):
    session = db.session
    ns = seed_account(session)
    sub = monthly_subscription_lot(session, ns)
    purchase = pack_purchase(session, ns)
    source = session.get(cases.FinancialTransaction, sub.tx)
    assert cases.classify_allocation_basis(session, source, [], 0) == "none"
    assert cases.classify_allocation_basis(
        session, source, [{"financial_line_id": sub.line, "attributed_principal_minor": 10000}], 10000) == "full"
    assert cases.classify_allocation_basis(
        session, source, [{"financial_line_id": sub.line, "attributed_principal_minor": 5000}], 5000) == "derived"
    pack = session.get(cases.FinancialTransaction, purchase.tx)
    assert cases.classify_allocation_basis(
        session, pack, [{"financial_line_id": purchase.line, "attributed_principal_minor": 300}], 300) == "single_line"


@pytest.mark.postgres
@PG
def test_postgres_a_forged_allocation_basis_is_refused_at_commit(monkeypatch):
    engine = _engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed_account(session)
            sub = monthly_subscription_lot(session, ns)
            session.commit()
            monkeypatch.setattr(cases, "classify_allocation_basis", lambda *a, **k: "full")
            with pytest.raises(sa.exc.DBAPIError, match="allocation basis does not match"):
                dispute(session, ns, sub.tx, f"dp_{ns.suffix}", {sub.line: 5000}, "opened")
                session.commit()
            session.rollback()
    finally:
        engine.dispose()


@pytest.mark.postgres
@PG
def test_postgres_a_derived_version_never_reaches_credit_evaluation(monkeypatch):
    engine = _engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed_account(session)
            sub = monthly_subscription_lot(session, ns)
            session.commit()
            # Bypass the service's D5 refusal: the database refuses the evaluation itself.
            monkeypatch.setattr(effects, "AUTHORITATIVE_ALLOCATION_BASES", frozenset(cases.ALLOCATION_BASES))
            with pytest.raises(sa.exc.DBAPIError, match="D5: a derived case allocation"):
                dispute(session, ns, sub.tx, f"dp_{ns.suffix}", {sub.line: 5000}, "opened")
                session.commit()
            session.rollback()
    finally:
        engine.dispose()


@pytest.mark.postgres
@PG
def test_postgres_evaluation_amounts_must_reconcile_with_their_effects_f4(monkeypatch):
    engine = _engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed_account(session)
            purchase = pack_purchase(session, ns)
            session.commit()
            # Bypass the service check and drop the effects an evaluation claims: commit is refused.
            monkeypatch.setattr(effects, "_reconcile_evaluation", lambda *a, **k: None)
            original = effects._write_effect

            def short(session, **kwargs):
                if kwargs.get("effect_type") == "hold":
                    kwargs = {**kwargs, "amount": kwargs["amount"] - 1}
                return original(session, **kwargs)

            monkeypatch.setattr(effects, "_write_effect", short)
            with pytest.raises(sa.exc.DBAPIError, match="do not reconcile"):
                dispute(session, ns, purchase.tx, f"dp_{ns.suffix}", {purchase.line: 1000}, "opened")
                session.commit()
            session.rollback()
    finally:
        engine.dispose()


def test_the_service_refuses_an_unreconciled_evaluation_f4(db, monkeypatch):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, ns)
    original = effects._write_effect

    def short(session, **kwargs):
        if kwargs.get("effect_type") == "hold":
            kwargs = {**kwargs, "amount": kwargs["amount"] - 1}
        return original(session, **kwargs)

    monkeypatch.setattr(effects, "_write_effect", short)
    with pytest.raises(effects.FinancialEffectError, match="do not reconcile"):
        dispute(session, ns, purchase.tx, f"dp_{ns.suffix}", {purchase.line: 1000}, "opened")
    session.rollback()
