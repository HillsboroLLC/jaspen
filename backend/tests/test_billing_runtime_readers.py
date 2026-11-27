"""I5: the readers family. Modern organizations answered in today's response shapes, from the authorities only.

D18 row 17 (readers), ADR-0001 projection rule and derived-field dictionary, Constitution Article 9 (every
number decomposes). The modern organization here is built through the accepted Phase 4, 6, 8 and 12
commands, then assigned to the modern model. Before the assignment its legacy columns are deliberately
filled with misleading values (plan, seats, overrides, meters, the owner's personal plan and balance):
every assertion that a projected value equals its authority also proves those columns are never read.
Every amount and policy number is a test fixture. Runs on SQLite, or PostgreSQL with TEST_DATABASE_URL.
"""

from datetime import timedelta
import random
import uuid

import pytest
import sqlalchemy as sa
from flask_jwt_extended import create_access_token

import app.billing_runtime_readers as readers
import app.orgs as orgs
from app import billing_cutover as bc
from app.billing_config import DEFAULT_PLAN_CATALOG, get_plan_catalog, get_usage_meter_state, tokens_to_credits
from app.billing_projections import ProjectionIsolationError, project_plan_terms
from app.billing_seats import open_seat_commitment, record_seat_funding_attribution
from app.models import (
    CreditLedgerEntry,
    CreditLot,
    IdempotencyRegistry,
    Organization,
    OrganizationMember,
    User,
)
from app.models_billing_identity import ASSIGNMENT_RULE_VERSION, BillingModelAssignment
from app.models_billing_phase4 import BillingSubscription, CreditPeriod, EntitlementDefinition, EntitlementInstance
from app.models_billing_phase8 import SeatCommitment
from app.routes.billing import _usage_warning_fields
from tests.test_billing_ai_operations import account as funded_account
from tests.test_billing_ai_operations import capacity, db_now, pricing
from tests.test_billing_enterprise_contracts import DELIVERIES, _user as p11_user
from tests.test_billing_projections import assert_pure, row_counts, settled_operation


ALL = ",".join(bc.FAMILIES)
WITHOUT_READERS = ",".join(bc.FAMILIES[:-1])
POISON_SEATS = 99
POISON_BALANCE = 123_456_789


@pytest.fixture
def readers_on(monkeypatch):
    monkeypatch.setenv(bc.SETTING, ALL)


# ---------------------------------------------------------------------------
# Fixtures: a modern organization from the accepted commands
# ---------------------------------------------------------------------------

def _poison_legacy_columns(session, ns):
    """Legacy columns a modern organization must never be read through (set before the assignment)."""
    org = session.get(Organization, ns.org)
    org.plan_key = "enterprise"
    org.max_total_paid_seats = POISON_SEATS
    org.seat_policy_overrides = {"creator": 50, "collaborator": 50}
    org.settings = {"thinking_power": {"remaining": POISON_BALANCE, "cycle_reset_at": "2020-01-01T00:00:00"}}
    owner = session.get(User, ns.owner)
    owner.subscription_plan, owner.subscription_status = "business", "active"
    owner.credits_remaining = POISON_BALANCE
    owner.ui_preferences = {"thinking_power": {"remaining": POISON_BALANCE, "cycle_reset_at": "2020-01-01"}}
    session.flush()


def _assign(session, ns):
    """Mark the organization modern, as ``establish_modern_billing_identity`` does (test-only shortcut: the
    accepted Phase 4-12 records already carry the billing account, which the command creates itself)."""
    registry = IdempotencyRegistry(
        id=str(uuid.uuid4()), namespace=bc.NAMESPACE, key=f"organization:{ns.org}", request_fingerprint="0" * 64,
        state="completed", claimed_at=db_now(session), completed_at=db_now(session),
    )
    session.add(registry)
    session.flush()
    session.add(BillingModelAssignment(
        id=str(uuid.uuid4()), organization_id=ns.org, billing_account_id=ns.account, model="modern",
        rule_version=ASSIGNMENT_RULE_VERSION, assigned_by_user_id=ns.owner, origin_type="test",
        origin_id=f"test:{ns.org}", footprint_json={"checked_users": [], "codes": []},
        request_fingerprint="0" * 64, idempotency_registry_id=registry.id, assigned_at=db_now(session),
    ))
    session.flush()


def modern_org(session, *, plan="team", members=1, credits=500, included_seats=None, poison=True):
    """A funded modern organization on ``plan`` (the definition key), with pricing and capacity for AI use."""
    ns = funded_account(session, members=members, credits=credits)
    definition = session.get(EntitlementDefinition, ns.sub.instance.entitlement_definition_id)
    # The canonical keys: plan.free, plan.<plan>.monthly|annual (this fixture's subscription is monthly).
    key = plan if plan.startswith("pro-") else ("plan.free" if plan == "free" else f"plan.{plan}.monthly")
    definition.key, definition.version = key, random.randint(10_000, 2**30)
    if included_seats is not None:
        definition.capability_json = {"schema_version": 1,
                                      "capabilities": {"analysis": True, "included_seats": included_seats}}
    session.flush()
    ns.tier = key
    ns.pricing = pricing(session)
    ns.capacity = capacity(session, [key])
    if poison:
        _poison_legacy_columns(session, ns)
    _assign(session, ns)
    ns.definition = definition
    return ns


def legacy_org(session, *, plan="team", members=("creator",)):
    owner = p11_user(session, "legacy-owner")
    user = session.get(User, owner)
    user.subscription_plan, user.subscription_status = plan, "active"
    org = Organization(id=f"legacy-{uuid.uuid4().hex[:10]}", name="Legacy", slug=f"legacy-{uuid.uuid4().hex[:10]}",
                       owner_user_id=owner, plan_key=plan, max_total_paid_seats=4,
                       seat_policy_overrides={"viewer": 2})
    session.add(org)
    session.flush()
    session.add(OrganizationMember(organization_id=org.id, user_id=owner, role="owner", status="active"))
    for role in members:
        session.add(OrganizationMember(organization_id=org.id, user_id=p11_user(session, "legacy-member"),
                                       role=role, status="active"))
    user.active_organization_id = org.id
    session.flush()
    return org


def context(session, ns):
    return bc.modern_context(session, family="readers", organization_id=ns.org,
                             config=bc.CutoverConfig(frozenset(bc.FAMILIES), ()))


# ---------------------------------------------------------------------------
# Independent authority reads (the tests' own queries, not the module's)
# ---------------------------------------------------------------------------

def ledger_available(session, account_id, at):
    return int(session.execute(
        sa.select(sa.func.coalesce(sa.func.sum(CreditLedgerEntry.available_delta), 0))
        .join(CreditLot, CreditLot.id == CreditLedgerEntry.lot_id)
        .where(CreditLedgerEntry.billing_account_id == account_id, CreditLot.available_at <= at,
               sa.or_(CreditLot.expires_at.is_(None), CreditLot.expires_at > at))
    ).scalar_one())


def settled_since(session, account_id, starts_at):
    return int(session.execute(
        sa.select(sa.func.coalesce(sa.func.sum(-CreditLedgerEntry.held_delta), 0)).where(
            CreditLedgerEntry.billing_account_id == account_id, CreditLedgerEntry.entry_type == "settlement",
            CreditLedgerEntry.effective_at >= starts_at)
    ).scalar_one())


def _naive(value):
    return value.replace(tzinfo=None) if value.tzinfo is None else \
        value.astimezone(__import__("datetime").timezone.utc).replace(tzinfo=None)


# ---------------------------------------------------------------------------
# Usage meter: projection equals authority (Article 9)
# ---------------------------------------------------------------------------

def test_usage_meter_equals_the_ledger_entitlement_and_period_authorities(db):
    session = db.session
    ns = modern_org(session, members=2)
    settled_operation(session, ns, ns.members[1])
    at = db_now(session)
    meter = readers.modern_usage_meter_state(session, context=context(session, ns), user_id=ns.owner, at=at)

    period = session.get(CreditPeriod, ns.period.id)
    lot = session.get(CreditLot, ns.lot.id)
    used = settled_since(session, ns.account, period.starts_at)
    assert used > 0
    assert meter["scope"] == "organization" and meter["organization_id"] == ns.org
    assert meter["plan_key"] == "team"  # the entitlement, not the "enterprise" row or the owner's "business"
    assert meter["monthly_limit"] == ns.definition.funding_policy_json["credit_amount"] == 500
    assert meter["cycle_limit"] == lot.original_amount
    assert meter["remaining"] == ledger_available(session, ns.account, at)
    assert meter["used"] == used  # the whole organization's settlements, including the other member's
    # Every number decomposes: the period allocation is what was used plus what remains of it.
    assert meter["cycle_limit"] == meter["used"] + meter["monthly_remaining"]
    assert meter["reset_at"] == _naive(period.starts_at)
    assert meter["next_allocation_at"] == _naive(period.ends_at)
    assert meter["grace_tokens"] == 0 and meter["overage_tokens"] == 0
    assert meter["persistent_credits"] == 0 and meter["founder_credits"] == 0
    assert meter["remaining"] != POISON_BALANCE and meter["not_available"] == []
    assert meter["billing_model"] == "modern" and meter["billing_account_id"] == ns.account


def test_usage_meter_has_the_legacy_keys(db):
    session = db.session
    legacy = legacy_org(session)
    owner = session.get(User, legacy.owner_user_id)
    legacy_keys = set(get_usage_meter_state(owner, {}))
    session.rollback()
    ns = modern_org(session)
    meter = readers.modern_usage_meter_state(session, context=context(session, ns), user_id=ns.owner)
    assert legacy_keys <= set(meter)


def test_a_missing_period_or_plan_is_reported_not_available_never_invented(db):
    session = db.session
    ns = modern_org(session)
    later = db_now(session) + timedelta(days=40)  # the funded period has ended and none covers this moment
    meter = readers.modern_usage_meter_state(session, context=context(session, ns), at=later)
    assert meter["cycle_limit"] is None and meter["used"] is None and meter["reset_at"] is None
    assert {"cycle_limit", "used", "reset_at", "monthly_remaining"} <= set(meter["not_available"])


def test_an_unrecognized_plan_definition_fails_closed(db):
    session = db.session
    ns = modern_org(session, plan="pro-unknown")
    ctx = context(session, ns)
    assert readers.modern_usage_meter_state(session, context=ctx)["plan_key"] is None
    gates = readers.modern_org_gates(session, context=ctx)
    assert gates["plan_key"] is None and "plan_key" in gates["not_available"]
    state = orgs._modern_collaboration_state(gates)
    assert state["can_invite"] is False and state["reason"] == orgs.COLLABORATION_DENIED_PLAN


def test_a_contract_plan_is_enterprise_and_definition_keys_follow_the_catalog():
    assert readers.public_plan_key("enterprise-contract:x", "enterprise_contract", {}) == "enterprise_custom"
    assert readers.public_plan_key("plan.free", "free", {}) == "free"
    for plan in ("starter", "essential", "team", "business", "enterprise_custom"):
        for interval in ("monthly", "annual"):
            assert readers.parse_plan_definition_key(f"plan.{plan}.{interval}") == (plan, interval)
            assert readers.public_plan_key(f"plan.{plan}.{interval}", "subscription", {}) == plan
        assert readers.parse_plan_definition_key(f"plan.{plan}") == (plan, None)
    for unrecognized in ("team", "plan.enterprise", "plan.", "plan.unknown", "pro-123", "PLAN.team",
                         "plan.team.weekly", "plan.team.monthly.x", "plan..monthly", "plan.monthly",
                         "plan.free.monthly"):
        assert readers.public_plan_key(unrecognized, "subscription", {}) is None
    assert readers.public_plan_key(None, None, {}) is None


def test_the_member_view_requires_an_active_membership(db):
    session = db.session
    ns = modern_org(session)
    outsider = p11_user(session, "outsider")
    with pytest.raises(ProjectionIsolationError):
        readers.modern_usage_meter_state(session, context=context(session, ns), user_id=outsider)


def test_member_attributed_credits_are_spendable_only_by_that_member(db):
    session = db.session
    ns = modern_org(session, members=2)
    lot = session.get(CreditLot, ns.lot.id)
    ctx = context(session, ns)
    pool = readers.modern_usage_meter_state(session, context=ctx)["remaining"]
    lot.member_attribution_id = ns.members[1]
    session.flush()
    assert readers.modern_usage_meter_state(session, context=ctx, user_id=ns.owner)["remaining"] == pool - \
        ledger_available(session, ns.account, db_now(session))
    assert readers.modern_usage_meter_state(session, context=ctx, user_id=ns.members[1])["remaining"] == pool


# ---------------------------------------------------------------------------
# GET /api/v1/billing/status
# ---------------------------------------------------------------------------

def _status(session, ns, **kwargs):
    owner = session.get(User, ns.owner)
    return readers.modern_billing_status(session, context=context(session, ns), user=owner, app_config={},
                                         usage_warning_fields=_usage_warning_fields, **kwargs)


def test_status_payload_keeps_every_legacy_key_and_projects_each_from_the_authorities(
        db, client, test_user, auth_headers, monkeypatch):
    legacy_keys = set(client.get("/api/v1/billing/status", headers=auth_headers).get_json())
    session = db.session
    ns = modern_org(session, members=2)
    settled_operation(session, ns, ns.members[1])
    import app.routes.billing as billing_routes

    def forbidden(*args, **kwargs):
        raise AssertionError("a modern status read never reaches the processor")

    monkeypatch.setattr(billing_routes.stripe.Subscription, "retrieve", forbidden)
    status = _status(session, ns)
    assert legacy_keys <= set(status)

    meter = readers.modern_usage_meter_state(session, context=context(session, ns), user_id=ns.owner)
    subscription = session.get(BillingSubscription, ns.sub.subscription.id)
    assert status["plan_key"] == status["effective_plan_key"] == "team"
    assert status["plan"] == get_plan_catalog({})["team"]
    assert status["subscription_status"] == "active" and status["cancel_at_period_end"] is False
    assert status["billing_interval"] == "monthly" and status["scheduled_plan_change"] is None
    assert status["current_period_end"] == _naive(subscription.term_ends_at).isoformat()
    assert status["credits_remaining"] == tokens_to_credits(meter["remaining"], precision=1)
    assert status["credits_used"] == tokens_to_credits(meter["used"], precision=1)
    assert status["monthly_credit_limit"] == tokens_to_credits(500, precision=0)
    assert status["cycle_credit_limit"] == tokens_to_credits(meter["cycle_limit"], precision=0)
    assert status["cycle_reset_at"] == meter["reset_at"].isoformat()
    assert status["usage_scope"] == "organization" and status["access_restricted"] is False
    assert status["credit_block_limit"] == status["credit_soft_stop_limit"] == status["cycle_credit_limit"]
    assert status["has_300k_limited_time"] is False and status["is_founder"] is False
    assert status["stripe_subscription_id"] == subscription.external_subscription_id
    assert status["stripe_customer_id"] is None  # the account has no bound processor customer
    expected = _usage_warning_fields(meter["cycle_limit"], meter["used"])
    assert (status["usage_percent"], status["usage_warning_level"]) == (
        expected["usage_percent"], expected["usage_warning_level"])
    assert status["is_admin"] is False and status["billing_model"] == "modern"
    assert status["not_available"] == []


def test_status_maps_subscription_states_to_the_spellings_the_frontend_reads(db):
    session = db.session
    ns = modern_org(session)
    subscription = session.get(BillingSubscription, ns.sub.subscription.id)
    subscription.state = "cancel_at_period_end"
    session.flush()
    status = _status(session, ns)
    assert status["subscription_status"] == "active" and status["cancel_at_period_end"] is True
    subscription.state = "past_due"
    session.flush()
    assert _status(session, ns)["subscription_status"] == "past_due"


def test_the_interval_comes_from_the_subscription_then_the_plan_definition(db):
    session = db.session
    ns = modern_org(session)
    assert _status(session, ns)["billing_interval"] == "monthly"
    subscription = session.get(BillingSubscription, ns.sub.subscription.id)
    subscription.interval = "custom"
    session.flush()
    assert _status(session, ns)["billing_interval"] == "monthly"  # plan.team.monthly
    ns.definition.key = "plan.team"
    session.flush()
    status = _status(session, ns)
    assert status["billing_interval"] is None and "billing_interval" in status["not_available"]


def test_an_admin_flag_never_impersonates_a_plan(db):
    session = db.session
    ns = modern_org(session, plan="starter")
    status = _status(session, ns, is_admin=True)
    assert status["is_admin"] is True
    assert status["plan_key"] == status["effective_plan_key"] == "starter"
    assert status["credits_used"] == tokens_to_credits(0, precision=1)


def test_purchased_and_non_expiring_credits_come_from_their_lots(db):
    session = db.session
    ns = modern_org(session)
    at = db_now(session)
    terms = project_plan_terms(session, billing_account_id=ns.account, at=at)
    assert terms["period"]["purchased_in_period"] == 0 and terms["non_expiring_available"] == 0
    assert terms["monthly_credit_amount"] == 500 and terms["period"]["allocated"] == ns.lot.original_amount


# ---------------------------------------------------------------------------
# Organization gates: plan, seat policy, seat limit, collaboration
# ---------------------------------------------------------------------------

def _commit_seats(session, ns, quantity):
    subscription = session.get(BillingSubscription, ns.sub.subscription.id)
    attribution, _state = record_seat_funding_attribution(
        session, billing_account_id=ns.account, subscription_id=subscription.id, financial_line_id=ns.sub.line,
        seat_source="included", term_starts_at=subscription.term_starts_at, term_ends_at=subscription.term_ends_at,
        evidence_reference=f"adapter:{ns.sub.line}", actor_type="system", actor_id="i5-test",
    )
    commitment, _state = open_seat_commitment(
        session, billing_account_id=ns.account, subscription_id=subscription.id, quantity=quantity,
        attribution_ids=[attribution.id], opened_at=subscription.term_starts_at, actor_type="system",
        actor_id="i5-test", delivery_obligations=DELIVERIES,
    )
    return commitment


def test_gates_read_the_entitlement_and_the_seat_commitment_never_the_legacy_columns(db, readers_on):
    session = db.session
    ns = modern_org(session, members=2, included_seats=3)
    org = session.get(Organization, ns.org)
    gates = orgs.modern_org_gates(org)
    assert gates["max_total_paid_seats"] == 3 and gates["seat_limit_source"] == "plan_included_seats"
    commitment = _commit_seats(session, ns, 3)
    gates = orgs.modern_org_gates(org)
    assert gates["max_total_paid_seats"] == session.get(SeatCommitment, commitment.id).quantity
    assert gates["seat_limit_source"] == "seat_commitment"

    payload = orgs.org_payload(org)
    assert payload["plan_key"] == "team" and payload["max_total_paid_seats"] == 3
    assert payload["seat_policy_overrides"] == {}
    assert payload["seat_policy"] == orgs.serialize_seat_policy("team")
    assert payload["mfa_policy"] == orgs.default_mfa_policy_for_plan("team")
    usage = orgs.build_seat_usage(org)
    assert usage["total_paid_limit"] == 3 and usage["total_paid_used"] == gates["seat_occupancy"] == 2
    assert orgs.role_has_capacity(org, "creator") is True  # 2 of 3 paid seats
    session.add(OrganizationMember(organization_id=org.id, user_id=p11_user(session, "third"), role="creator",
                                   status="active"))
    session.flush()
    assert orgs.role_has_capacity(org, "creator") is False  # the commitment, not the poisoned 99
    assert orgs.role_has_capacity(org, "viewer") is True


def test_without_a_seat_authority_no_paid_seat_is_authorized(db, readers_on):
    session = db.session
    ns = modern_org(session)
    org = session.get(Organization, ns.org)
    gates = orgs.modern_org_gates(org)
    assert gates["max_total_paid_seats"] == 0 and "max_total_paid_seats" in gates["not_available"]
    assert orgs.role_has_capacity(org, "creator") is False


def test_collaboration_follows_the_modern_plan_and_subscription_standing(db, readers_on):
    session = db.session
    ns = modern_org(session)
    org = session.get(Organization, ns.org)
    state = orgs.org_collaboration_state(org)
    assert state == {"plan_key": "team", "public_plan_key": "team", "entitled": True, "billing_current": True,
                     "can_invite": True, "reason": None}
    subscription = session.get(BillingSubscription, ns.sub.subscription.id)
    subscription.state = "past_due"
    session.flush()
    state = orgs.org_collaboration_state(org)
    assert state["entitled"] is True and state["can_invite"] is False
    assert state["reason"] == orgs.COLLABORATION_DENIED_BILLING
    owner = session.get(User, ns.owner)
    owner.active_organization_id = org.id
    session.flush()
    assert orgs.user_collaboration_state(owner) == state  # the owner's personal "business" plan never answers


def test_a_sub_team_modern_plan_cannot_collaborate_whatever_its_legacy_row_says(db, readers_on):
    session = db.session
    ns = modern_org(session, plan="essential")
    org = session.get(Organization, ns.org)
    assert org.plan_key == "enterprise"  # poisoned legacy column
    state = orgs.org_collaboration_state(org)
    assert state["entitled"] is False and state["reason"] == orgs.COLLABORATION_DENIED_PLAN
    assert orgs.seat_policy_for_org(org) == {**orgs.seat_policy_for_plan("essential"), "owner": 1}


def test_organization_access_payload_reads_the_modern_plan(db, readers_on):
    session = db.session
    ns = modern_org(session, plan="essential")
    owner = session.get(User, ns.owner)
    owner.active_organization_id = ns.org
    session.flush()
    payload = orgs.organization_access_payload_for_user(owner)
    assert payload["active_organization_plan_key"] == "essential"
    assert payload["can_access_team"] is False and payload["can_access_enterprise_admin"] is False


# ---------------------------------------------------------------------------
# Reads never write
# ---------------------------------------------------------------------------

def _pure(session, fn):
    return assert_pure(session, lambda _session: fn())


def test_every_reader_and_gate_makes_zero_writes(db, readers_on):
    session = db.session
    ns = modern_org(session, members=2, included_seats=3)
    settled_operation(session, ns, ns.members[1])
    org = session.get(Organization, ns.org)
    owner = session.get(User, ns.owner)
    owner.active_organization_id = org.id
    session.commit()
    ctx = context(session, ns)
    at = db_now(session)  # fixed, so two calls are comparable (the default is the database clock)
    for fn in (
        lambda: readers.modern_usage_meter_state(session, context=ctx, user_id=ns.owner, at=at),
        lambda: readers.modern_billing_status(session, context=ctx, user=owner, app_config={},
                                              usage_warning_fields=_usage_warning_fields, at=at),
        lambda: readers.modern_org_gates(session, context=ctx, at=at),
        lambda: project_plan_terms(session, billing_account_id=ns.account, member_user_id=ns.owner, at=at),
        lambda: orgs.org_payload(org),
        lambda: orgs.build_seat_usage(org),
        lambda: orgs.role_has_capacity(org, "creator"),
        lambda: orgs.org_collaboration_state(org),
        lambda: orgs.user_collaboration_state(owner),
        lambda: orgs.organization_access_payload_for_user(owner),
        lambda: orgs.mfa_policy_for_org(org),
    ):
        _pure(session, fn)


def test_a_caller_pending_change_is_neither_flushed_nor_lost(db, readers_on):
    session = db.session
    ns = modern_org(session)
    org = session.get(Organization, ns.org)
    before = row_counts(session)
    pending = User(id=f"pending-{uuid.uuid4().hex[:8]}", email=f"p-{uuid.uuid4().hex[:8]}@example.test",
                   name="pending", password_hash="x")
    session.add(pending)
    readers.modern_usage_meter_state(session, context=context(session, ns))
    orgs.org_payload(org)
    assert pending in session.new and row_counts(session) == before


# ---------------------------------------------------------------------------
# Dispatch: legacy unchanged; modern with the family off answers nobody
# ---------------------------------------------------------------------------

LEGACY_READS = (
    lambda org, owner: orgs.org_payload(org),
    lambda org, owner: orgs.build_seat_usage(org),
    lambda org, owner: orgs.seat_policy_for_org(org),
    lambda org, owner: orgs.seat_policy_overrides_for_org(org),
    lambda org, owner: orgs.serialize_seat_policy(org),
    lambda org, owner: orgs.role_has_capacity(org, "creator"),
    lambda org, owner: orgs.org_collaboration_state(org),
    lambda org, owner: orgs.user_collaboration_state(owner),
    lambda org, owner: orgs.organization_access_payload_for_user(owner),
    lambda org, owner: orgs.mfa_policy_for_org(org),
)


def test_legacy_organizations_never_reach_the_readers_and_answer_identically(db, monkeypatch):
    session = db.session
    org = legacy_org(session)
    owner = session.get(User, org.owner_user_id)
    session.commit()
    baseline = [read(org, owner) for read in LEGACY_READS]
    assert baseline[0]["plan_key"] == "team" and baseline[0]["max_total_paid_seats"] == 4
    assert baseline[3] == {"viewer": 2}

    def forbidden(*args, **kwargs):
        raise AssertionError("a legacy organization never reaches the readers family")

    monkeypatch.setattr(readers, "modern_org_gates", forbidden)
    modern_org(session)  # a modern organization now exists elsewhere
    session.commit()
    for families in ("", WITHOUT_READERS, ALL):
        monkeypatch.setenv(bc.SETTING, families)
        assert [read(org, owner) for read in LEGACY_READS] == baseline


def test_a_modern_organization_with_the_readers_family_off_is_answered_by_nobody(db, monkeypatch):
    session = db.session
    ns = modern_org(session)
    org = session.get(Organization, ns.org)
    owner = session.get(User, ns.owner)
    owner.active_organization_id = org.id
    session.commit()
    monkeypatch.setenv(bc.SETTING, WITHOUT_READERS)
    for read in LEGACY_READS:
        with pytest.raises(bc.BillingFamilyDisabledError):
            read(org, owner)


def _headers(app, user_id):
    with app.app_context():
        return {"Authorization": f"Bearer {create_access_token(identity=str(user_id))}"}


def test_team_routes_answer_from_the_modern_records(app, client, db, monkeypatch):
    session = db.session
    ns = modern_org(session, members=2, included_seats=3)
    org = session.get(Organization, ns.org)
    org.max_admin_seats, org.max_creator_seats, org.max_collaborator_seats = 9, 9, 9  # legacy columns
    owner = session.get(User, ns.owner)
    owner.active_organization_id = ns.org
    session.commit()
    headers = _headers(app, ns.owner)
    monkeypatch.setenv(bc.SETTING, ALL)
    summary = client.get("/api/v1/team/summary", headers=headers)
    assert summary.status_code == 200, summary.get_json()
    body = summary.get_json()
    assert body["organization"]["plan_key"] == "team"
    assert body["organization"]["max_total_paid_seats"] == 3
    assert body["seat_usage"]["total_paid_limit"] == 3
    teams = client.get(f"/api/v1/teams/{ns.org}", headers=headers)
    assert teams.status_code == 200, teams.get_json()
    assert teams.get_json()["organization"]["plan"] == "team"
    assert teams.get_json()["organization"]["max_total_paid_seats"] == 3
    assert {teams.get_json()["organization"][k] for k in
            ("max_admin_seats", "max_creator_seats", "max_collaborator_seats")} == {None}

    monkeypatch.setenv(bc.SETTING, WITHOUT_READERS)
    refused = client.get("/api/v1/team/summary", headers=headers)
    assert refused.status_code == 503 and refused.get_json()["error"] == "billing_family_disabled"
    refused = client.get(f"/api/v1/teams/{ns.org}", headers=headers)
    assert refused.status_code == 503


def test_the_legacy_seat_policy_edit_of_a_modern_organization_answers_409(app, client, db, monkeypatch):
    session = db.session
    ns = modern_org(session)
    owner = session.get(User, ns.owner)
    owner.active_organization_id = ns.org
    session.commit()
    monkeypatch.setenv(bc.SETTING, ALL)
    response = client.patch("/api/v1/team/seat-policy", json={"seat_policy_overrides": {"viewer": 3}},
                            headers=_headers(app, ns.owner))
    assert response.status_code == 409 and response.get_json()["error"] == "billing_model_conflict"
    session.expire_all()
    assert session.get(Organization, ns.org).seat_policy_overrides == {"creator": 50, "collaborator": 50}


def test_free_allowance_unit_matches_the_ledger_unit():
    """The ledger and the legacy meters share internal credit units (I1 footprint check uses the same)."""
    assert tokens_to_credits(DEFAULT_PLAN_CATALOG["free"]["monthly_credits"], precision=0) == 300
