"""I2: the credit-funding family runtime: D2 test catalog, D4 Free allowance, placeholders, CLI."""

from datetime import timedelta
import importlib.util
import json

import pytest

from app import billing_cutover as bc
from app import billing_runtime_funding as funding
from app.models import (
    CreditLedgerEntry,
    CreditLot,
    EntitlementDefinition,
    EntitlementInstance,
)
from app.models_billing_phase5 import CommunicationOutbox
from tests.test_billing_cutover import _establish, _org, _user

FUNDING_ON = bc.CutoverConfig(frozenset(bc.FAMILIES[:3]), ())
ALL_I2 = ",".join(bc.FAMILIES[:3])


@pytest.fixture
def families(monkeypatch):
    monkeypatch.setenv(bc.SETTING, ALL_I2)


def _modern_org(session):
    owner = _user(session)
    org = _org(session, owner)
    assignment, _state = _establish(session, org)
    session.commit()
    return owner, org, assignment


def _catalog(session, app, approver):
    results = funding.define_test_catalog(
        session, approver_user_id=approver.id, app_config=app.config,
        effective_at=bc._database_now(session) - timedelta(days=1))
    session.commit()
    return results


def test_definition_keys_follow_the_approved_convention():
    assert funding.plan_definition_key("free") == "plan.free"
    assert funding.plan_definition_key("team", "annual") == "plan.team.annual"
    assert funding.plan_tier_key("plan.team.annual") == "plan.team"
    assert funding.plan_tier_key("plan.free") == "plan.free"
    with pytest.raises(funding.FundingRuntimeError):
        funding.plan_definition_key("team")
    with pytest.raises(funding.FundingRuntimeError):
        funding.plan_tier_key("enterprise-contract:abc")


@pytest.mark.parametrize("variable,value", [("APP_ENV", "production"), ("STRIPE_SECRET_KEY", "sk_live_x")])
def test_placeholder_obligations_are_refused_in_production(monkeypatch, variable, value):
    assert funding.placeholder_obligations("credit_period_funded") == [{
        "template_key": "credit_period_funded", "template_version": "unapproved-v0", "channel": "none",
        "locale": "en-US"}]
    monkeypatch.setenv(variable, value)
    with pytest.raises(funding.FundingRuntimeError):
        funding.placeholder_obligations("credit_period_funded")


def test_the_test_catalog_copies_configured_values_and_is_refused_while_the_family_is_off(db, app):
    session = db.session
    approver = _user(session)
    session.commit()
    with pytest.raises(bc.BillingFamilyDisabledError):
        funding.define_test_catalog(session, approver_user_id=approver.id, app_config=app.config)
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv(bc.SETTING, ALL_I2)
        results = _catalog(session, app, approver)
        assert {key for key, _v, state in results if state == "inserted"} >= {
            "plan.free", "plan.starter.monthly", "plan.starter.annual", "plan.team.monthly",
            "plan.business.annual", "pack.credits_3000"}
        assert not any(key.startswith("plan.enterprise") for key, _v, _s in results)
        free = session.query(EntitlementDefinition).filter_by(key="plan.free").one()
        assert free.funding_policy_json == {"schema_version": 1, "period_kind": "free", "credit_amount": 300}
        assert free.capability_json["capabilities"]["pricing_label"] == "test"
        assert free.approval_evidence_reference == "founder-decision-D2-2026-11-26"
        assert free.approved_by_user_id == approver.id
        team = session.query(EntitlementDefinition).filter_by(key="plan.team.annual").one()
        assert team.capability_json["capabilities"]["included_seats"] == 3
        assert team.funding_policy_json["period_kind"] == "annual_monthly"
        assert team.funding_policy_json["credit_amount"] == 29_000
        pack = session.query(EntitlementDefinition).filter_by(key="pack.credits_3000").one()
        assert pack.funding_policy_json["purchase"]["unit_principal_minor"] == 1000
        assert pack.funding_policy_json["credit_amount"] == 3000
        # Re-running converges; a changed payload is refused rather than silently versioned.
        assert {state for _k, _v, state in _catalog(session, app, approver)} == {"unchanged"}
        free.funding_policy_json = {"schema_version": 1, "period_kind": "free", "credit_amount": 1}
        session.flush()
        with pytest.raises(funding.FundingRuntimeError, match="differs"):
            funding.define_test_catalog(session, approver_user_id=approver.id, app_config=app.config)
        session.rollback()


def test_each_modern_organization_owns_its_monthly_free_lot(db, app, families):
    session = db.session
    owner, org, assignment = _modern_org(session)
    context = bc.modern_context(session, family="credit_funding", organization_id=org.id)
    assert funding.allocate_free(session, context).outcome == "no_definition"
    session.rollback()
    _catalog(session, app, owner)
    first = funding.allocate_free(session, context)
    session.commit()
    assert (first.outcome, first.period_index, first.credit_amount) == ("inserted", 0, 300)
    lot = session.query(CreditLot).one()
    assert (lot.billing_account_id, lot.source_type, lot.original_amount) == (
        assignment.billing_account_id, "free_recurring", 300)
    instance = session.query(EntitlementInstance).one()
    assert (instance.source_type, instance.state, instance.subscription_id) == ("free", "active", None)
    assert session.query(CreditLedgerEntry).filter_by(lot_id=lot.id, entry_type="grant").count() == 1
    outbox = session.query(CommunicationOutbox).one()
    assert (outbox.channel, outbox.template_version) == ("none", "unapproved-v0")
    again = funding.allocate_free(session, context)
    session.commit()
    assert again.outcome == "duplicate"
    assert session.query(CreditLot).count() == 1


def test_free_allocation_is_unreachable_for_legacy_organizations_and_while_the_family_is_off(db, app):
    session = db.session
    owner = _user(session)
    legacy = _org(session, owner)
    session.commit()
    assert bc.modern_context(session, family="credit_funding", organization_id=legacy.id) is None
    _owner, modern, _assignment = _modern_org(session)
    with pytest.raises(bc.BillingFamilyDisabledError):
        bc.modern_context(session, family="credit_funding", organization_id=modern.id,
                          config=bc.CutoverConfig(frozenset(bc.FAMILIES[:2]), ()))


def test_period_index_tracks_calendar_months_from_the_anchor():
    from datetime import datetime, timezone

    anchor = datetime(2026, 1, 31, 12, tzinfo=timezone.utc)
    assert funding.period_index_at(anchor, anchor) == 0
    assert funding.period_index_at(anchor, datetime(2026, 2, 28, 11, tzinfo=timezone.utc)) == 0
    assert funding.period_index_at(anchor, datetime(2026, 2, 28, 12, tzinfo=timezone.utc)) == 1
    assert funding.period_index_at(anchor, datetime(2027, 1, 31, 12, tzinfo=timezone.utc)) == 12


# ---------------------------------------------------------------------------
# Operator command line
# ---------------------------------------------------------------------------

def _cli(app, argv, capsys):
    from tests.test_billing_migration import BACKEND

    spec = importlib.util.spec_from_file_location("billing_events", BACKEND / "scripts" / "billing_events.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    code = module.run(argv, app=app)
    return code, json.loads(capsys.readouterr().out or "null")


@pytest.mark.parametrize("variable,value", [("APP_ENV", "production"), ("STRIPE_SECRET_KEY", "sk_live_example")])
def test_the_command_line_refuses_a_production_runtime(app, capsys, monkeypatch, variable, value):
    monkeypatch.setenv(variable, value)
    code, out = _cli(app, ["allocate-free", "--confirm-write"], capsys)
    assert code == 2 and "production runtime" in out["error"]


def test_the_command_line_needs_confirmation_and_the_family(db, app, capsys, monkeypatch):
    session = db.session
    owner, org, _assignment = _modern_org(session)
    code, out = _cli(app, ["allocate-free"], capsys)
    assert code == 2 and "--confirm-write" in out["error"]
    code, out = _cli(app, ["process", "--limit", "0", "--confirm-write"], capsys)
    assert code == 2 and "--limit" in out["error"]
    code, out = _cli(app, ["allocate-free", "--confirm-write"], capsys)
    assert code == 3 and "not enabled" in out["error"]
    monkeypatch.setenv(bc.SETTING, ALL_I2)
    effective = (bc._database_now(session) - timedelta(days=1)).isoformat()
    code, out = _cli(app, ["define-test-catalog", "--approver-user-id", owner.id, "--effective-at", effective,
                           "--confirm-write"], capsys)
    assert code == 0 and {d["key"] for d in out["definitions"]} >= {"plan.free"}
    code, out = _cli(app, ["allocate-free", "--confirm-write"], capsys)
    assert code == 0
    assert [(o["organization_id"], o["outcome"]) for o in out["organizations"]] == [(org.id, "inserted")]
