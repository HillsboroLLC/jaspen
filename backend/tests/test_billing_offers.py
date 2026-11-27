"""Phase 10 trials, promotions, comps, and internal funding (D06/D07; P07, P08, P23;
D17 T-OFFER-01..04, T-ADMIN-01..06, T-OWNER internal/trial/promo isolation).

Service tests run against the ORM schema (SQLite, or an isolated PostgreSQL
schema when TEST_DATABASE_URL is set). ``test_sqlite_migration_*`` applies the
Phase 10 revision on SQLite. ``test_postgres_migrated_*`` runs against the fully
migrated disposable PostgreSQL database, where every Phase 3-10 guard is live.

All offer values below are test fixtures, not commercial terms.
"""

from concurrent.futures import ThreadPoolExecutor
import contextlib
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import threading
import uuid

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

from app import db as flask_db
from app.billing_entitlements import append_entitlement_transition
from app.billing_financial_effects import fund_credit_purchase
from app.billing_ledger import ordered_lot_balances
from app.billing_offers import (
    OfferConflictError,
    OfferDependencyError,
    OfferEligibilityError,
    OfferError,
    OfferIsolationError,
    OfferLimitError,
    OfferPermissionError,
    OfferPolicyRequiredError,
    OfferRetryError,
    expire_offer_entitlement,
    offer_terms,
    record_staff_billing_permission,
    redeem_credit_offer,
    revoke_staff_billing_permission,
)
from app.models import (
    BillingAccount,
    BillingRoleGrant,
    BillingStaffPermissionGrant,
    BillingStaffPermissionRevocation,
    CommunicationOutbox,
    CreditLedgerEntry,
    CreditLot,
    CreditOfferFunding,
    CreditOfferRedemption,
    DomainEvent,
    EntitlementDefinition,
    EntitlementEvent,
    EntitlementInstance,
    IdempotencyRegistry,
    Organization,
    User,
)
from tests.test_billing_financial_effects import pack_purchase


BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = str(BACKEND_DIR / "migrations")
REVISION = "f2b4d6e8a0c3"
PARENT = "e1a3c5b7d9f2"
PHASE10_TABLES = (
    "credit_offer_fundings", "credit_offer_redemptions",
    "billing_staff_permission_revocations", "billing_staff_permission_grants",
)
ANCHOR = datetime(2026, 1, 31, 15, 45, tzinfo=timezone.utc)
AT = ANCHOR + timedelta(days=2)
DELIVERIES = ({
    "template_key": "test-offer", "template_version": "test-v1",
    "channel": "test-channel", "locale": "en-US",
},)
SYSTEM = {"actor_type": "system", "actor_id": "phase10-offer-service"}
PROVISIONER = {"actor_type": "system", "actor_id": "phase10-provisioning"}
COMP_PERMISSION = "billing.comp.grant"
INTERNAL_PERMISSION = "billing.internal_funding.grant"
PG = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)


def _utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class Ns:
    def __init__(self, **values):
        self.__dict__.update(values)


# ---------------------------------------------------------------------------
# Seeding helpers (Flask session or plain migrated Session)
# ---------------------------------------------------------------------------

def _user(session, tag, label):
    user = User(
        id=f"p10-{label}-{tag}", email=f"p10-{label}-{tag}@example.test", name=f"Phase 10 {label}",
        password_hash="not-a-login-credential", subscription_plan="free",
        credits_remaining=0, seat_limit=1, max_seats=1,
    )
    session.add(user)
    session.flush()
    return user.id


def seed_account(session, suffix=None, *, status="proposed", currency="usd"):
    suffix = suffix or uuid.uuid4().hex[:10]
    owner = _user(session, suffix, "owner")
    organization = Organization(
        id=f"p10-org-{suffix}", name=f"Phase 10 {suffix}", slug=f"phase-10-{suffix}",
        owner_user_id=owner, plan_key="free",
    )
    session.add(organization)
    session.flush()
    account = BillingAccount(
        id=f"p10-account-{suffix}", organization_id=organization.id, currency=currency,
        account_anchor_at=ANCHOR, status=status,
    )
    session.add(account)
    session.flush()
    return Ns(suffix=suffix, account=account.id, org=organization.id, owner=owner)


def offer_definition(
    session, *, origin="trial", key=None, version=1, components=None, capabilities=None,
    per_account=1, total=1000, days=14, expiry="term_end", statuses=("proposed", "active"),
    approved=True, effective_at=None, retired_at=None, exclusivity_key=None, overrides=None,
):
    tag = uuid.uuid4().hex[:8]
    key = key or f"offer-{origin}-{tag}"
    components = [{"component": "base", "credit_amount": 500}] if components is None else components
    capabilities = {"advanced_analysis": True} if capabilities is None else capabilities
    offer = {
        "schema_version": 1, "origin": origin, "funding_source": "jaspen_test_budget",
        "owner": {"kind": "billing_account"},
        "eligibility": {"account_statuses": list(statuses)},
        "redemption_limits": {"per_account": per_account, "total": total},
        "term": {"kind": "fixed_days", "days": days},
        "credit_expiry": {"kind": expiry},
        "components": components,
    }
    offer.update(overrides or {})
    definition = EntitlementDefinition(
        id=f"p10-def-{tag}", key=key, version=version,
        exclusivity_key=exclusivity_key or f"offer-exclusive-{tag}",
        capability_json={"schema_version": 1, "capabilities": capabilities},
        funding_policy_json={
            "schema_version": 1, "period_kind": "none",
            "credit_amount": sum(c["credit_amount"] for c in components), "offer": offer,
        },
        effective_at=effective_at or ANCHOR - timedelta(days=30),
        retired_at=retired_at,
        approved_at=(ANCHOR - timedelta(days=30)) if approved else None,
        approval_evidence_reference="approval:phase10-test" if approved else None,
    )
    session.add(definition)
    session.flush()
    return definition.id


def staff(session, permission=COMP_PERMISSION, *, starts_at=None, ends_at=None):
    tag = uuid.uuid4().hex[:8]
    user_id = _user(session, tag, "staff")
    grant, state = record_staff_billing_permission(
        session, grant_command_id=f"grant-{tag}", user_id=user_id, permission=permission,
        starts_at=starts_at or ANCHOR, ends_at=ends_at,
        approval_evidence_reference="founder-approval:test", justification="test staff permission",
        **PROVISIONER,
    )
    assert state == "inserted"
    return Ns(user=user_id, grant=grant.id)


def staff_actor(member):
    return {
        "actor_type": "user", "actor_id": member.user, "reason_code": "service_recovery",
        "justification": "test comp justification", "evidence_reference": "ticket:test-1",
    }


def redeem(session, ns, definition_id, *, redemption_id=None, actor=None, deliveries=DELIVERIES):
    return redeem_credit_offer(
        session, billing_account_id=ns.account, entitlement_definition_id=definition_id,
        redemption_id=redemption_id or f"redeem-{uuid.uuid4().hex[:10]}",
        delivery_obligations=deliveries, **(actor or SYSTEM),
    )


def db_now(session):
    """The database clock the service uses (no caller time is accepted)."""
    from app.billing_offers import _database_now
    return _database_now(session)


def consume(session, account_id, lot_id, amount):
    """Test-only stand-in for delivered usage (Phase 12 settlement is not active)."""
    from app.billing_ledger import append_entry
    registry = IdempotencyRegistry(
        id=str(uuid.uuid4()), namespace="test_consumption", key=str(uuid.uuid4()),
        request_fingerprint="c" * 64, state="claimed", claimed_at=datetime.now(timezone.utc),
    )
    session.add(registry)
    session.flush()
    append_entry(session, CreditLedgerEntry(
        id=str(uuid.uuid4()), billing_account_id=account_id, lot_id=lot_id,
        entry_type="admin_adjustment", available_delta=-amount, held_delta=0,
        idempotency_registry_id=registry.id, effective_at=datetime.now(timezone.utc),
        actor_type="test", actor_id="consumption", reason_code="test_usage", evidence_json={},
    ))


def balance(session, lot_id):
    available, held = session.execute(
        sa.select(
            sa.func.coalesce(sa.func.sum(CreditLedgerEntry.available_delta), 0),
            sa.func.coalesce(sa.func.sum(CreditLedgerEntry.held_delta), 0),
        ).where(CreditLedgerEntry.lot_id == lot_id)
    ).one()
    return int(available), int(held)


def _counts(session):
    return tuple(session.query(model).count() for model in (
        CreditOfferRedemption, CreditOfferFunding, CreditLot, CreditLedgerEntry,
        EntitlementInstance, EntitlementEvent, DomainEvent, CommunicationOutbox,
    ))


# ---------------------------------------------------------------------------
# T-OFFER: only approved, complete, versioned offers grant entitlement and lots
# ---------------------------------------------------------------------------

def test_trial_grants_exact_entitlement_and_lot_once_and_replay_converges(db):
    session = db.session
    ns = seed_account(session)
    definition_id = offer_definition(session, days=14)
    redemption, fundings, lots, state = redeem(session, ns, definition_id, redemption_id="signup-1")
    assert state == "inserted"
    start = _utc(redemption.redeemed_at)
    assert abs(start - datetime.now(timezone.utc)) < timedelta(minutes=5)  # database time, not caller time
    end = start + timedelta(days=14)
    assert (redemption.origin, redemption.billing_account_id) == ("trial", ns.account)
    assert (_utc(redemption.term_starts_at), _utc(redemption.term_ends_at)) == (start, end)
    assert redemption.account_redemption_index == 1 and redemption.total_redemption_index == 1
    [lot] = lots
    assert (lot.source_type, lot.billing_account_id, lot.original_amount) == ("trial", ns.account, 500)
    assert (_utc(lot.available_at), _utc(lot.expires_at)) == (start, end)
    assert lot.member_attribution_id is None and lot.source_id == fundings[0].id
    assert balance(session, lot.id) == (500, 0)
    grant = session.query(CreditLedgerEntry).filter_by(lot_id=lot.id).one()
    assert grant.entry_type == "grant" and grant.reason_code == "offer_trial"
    assert fundings[0].funding_key == f"offer:{definition_id}:signup-1:base"  # D13
    instance = session.get(EntitlementInstance, redemption.entitlement_instance_id)
    assert (instance.state, instance.source_type, instance.source_id) == ("active", "trial", redemption.id)
    assert (_utc(instance.starts_at), _utc(instance.ends_at)) == (start, end)
    assert [e.to_state for e in session.query(EntitlementEvent).filter_by(
        entitlement_instance_id=instance.id).order_by(EntitlementEvent.created_at, EntitlementEvent.to_state.desc())
    ] == ["scheduled", "active"]
    event = session.get(DomainEvent, redemption.domain_event_id)
    assert event.event_type == "trial_started"
    assert event.event_key == f"trial_started:{definition_id}:signup-1"
    assert session.query(CommunicationOutbox).filter_by(domain_event_id=event.id).count() == 1

    before = _counts(session)
    for _ in range(2):
        again, again_fundings, again_lots, state = redeem(session, ns, definition_id, redemption_id="signup-1")
        assert state == "duplicate" and again.id == redemption.id
        assert _utc(again.redeemed_at) == start  # a retry keeps the original time
        assert [l.id for l in again_lots] == [lot.id] and again_fundings[0].id == fundings[0].id
    assert _counts(session) == before


def test_promotion_with_two_components_and_no_expiry_funds_each_component(db):
    session = db.session
    ns = seed_account(session)
    definition_id = offer_definition(
        session, origin="promotion", expiry="none", capabilities={},
        components=[{"component": "bonus", "credit_amount": 300}, {"component": "base", "credit_amount": 200}],
    )
    redemption, fundings, lots, state = redeem(session, ns, definition_id)
    assert state == "inserted" and redemption.entitlement_instance_id is None  # credits only
    assert sorted((f.funding_component, f.credit_amount) for f in fundings) == [("base", 200), ("bonus", 300)]
    assert {lot.source_type for lot in lots} == {"promotional"}
    assert all(lot.expires_at is None for lot in lots)
    assert session.get(DomainEvent, redemption.domain_event_id).event_type == "promotion_redeemed"


def _bad_definition(session, case):
    if case == "unapproved":
        return offer_definition(session, approved=False)
    if case == "not_effective":
        return offer_definition(session, effective_at=datetime.now(timezone.utc) + timedelta(days=1))
    if case == "retired":
        return offer_definition(session, retired_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    if case == "unknown_field":
        return offer_definition(session, overrides={"stackable": True})
    if case == "missing_limits":
        definition_id = offer_definition(session)
        definition = session.get(EntitlementDefinition, definition_id)
        policy = dict(definition.funding_policy_json)
        offer = dict(policy["offer"])
        offer.pop("redemption_limits")
        policy["offer"] = offer
        definition.funding_policy_json = policy
        session.flush()
        return definition_id
    if case == "components_mismatch":
        definition_id = offer_definition(session)
        definition = session.get(EntitlementDefinition, definition_id)
        definition.funding_policy_json = {**definition.funding_policy_json, "credit_amount": 999}
        session.flush()
        return definition_id
    if case == "unlimited":
        return offer_definition(session, capabilities={"unlimited_credits": True})
    if case == "open_term":
        return offer_definition(session, overrides={"term": {"kind": "open"}})
    if case == "unknown_origin":
        return offer_definition(session, origin="enterprise_contract")
    if case == "empty_offer":
        return offer_definition(session, components=[], capabilities={})
    if case == "recurring":
        definition_id = offer_definition(session)
        definition = session.get(EntitlementDefinition, definition_id)
        definition.funding_policy_json = {**definition.funding_policy_json, "period_kind": "free"}
        session.flush()
        return definition_id
    raise AssertionError(case)


@pytest.mark.parametrize("case", [
    "unapproved", "not_effective", "retired", "unknown_field", "missing_limits", "components_mismatch",
    "unlimited", "open_term", "unknown_origin", "empty_offer", "recurring",
])
def test_unapproved_or_incomplete_offers_fail_closed_without_mutation(db, case):
    session = db.session
    ns = seed_account(session)
    definition_id = _bad_definition(session, case)
    before = _counts(session)
    with pytest.raises(OfferDependencyError):
        redeem(session, ns, definition_id)
    assert _counts(session) == before


def test_member_attributed_owner_requires_a_policy_decision(db):
    session = db.session
    ns = seed_account(session)
    definition_id = offer_definition(session, overrides={"owner": {"kind": "member"}})
    with pytest.raises(OfferPolicyRequiredError):
        redeem(session, ns, definition_id)


def test_missing_definition_and_other_account_share_one_message(db):
    session = db.session
    ns = seed_account(session)
    with pytest.raises(OfferDependencyError, match="offer definition is not available"):
        redeem(session, ns, "p10-def-does-not-exist")
    with pytest.raises(OfferError, match="billing account is not available"):
        redeem_credit_offer(
            session, billing_account_id="p10-account-missing", entitlement_definition_id=offer_definition(session),
            redemption_id="x", delivery_obligations=DELIVERIES, **SYSTEM,
        )


def test_per_account_limit_spans_offer_versions_and_total_limit_spans_accounts(db):
    session = db.session
    first, second, third = (seed_account(session) for _ in range(3))
    key = f"offer-limited-{uuid.uuid4().hex[:6]}"
    v1 = offer_definition(session, key=key, version=1, per_account=1, total=2, capabilities={})
    v2 = offer_definition(session, key=key, version=2, per_account=1, total=2, capabilities={})
    redeem(session, first, v1)
    # A new version of the same offer does not reset the per-account limit.
    with pytest.raises(OfferLimitError):
        redeem(session, first, v2)
    redeem(session, second, v2)
    with pytest.raises(OfferLimitError):
        redeem(session, third, v1)
    rows = session.query(CreditOfferRedemption).filter_by(offer_key=key).order_by(
        CreditOfferRedemption.total_redemption_index).all()
    assert [(r.billing_account_id, r.account_redemption_index, r.total_redemption_index) for r in rows] == [
        (first.account, 1, 1), (second.account, 1, 2),
    ]


def test_ineligible_account_status_is_refused(db):
    session = db.session
    ns = seed_account(session, status="closed")
    with pytest.raises(OfferEligibilityError):
        redeem(session, ns, offer_definition(session))


def test_incompatible_entitlement_interval_is_refused(db):
    session = db.session
    ns = seed_account(session)
    exclusive = f"base-plan-{uuid.uuid4().hex[:6]}"
    redeem(session, ns, offer_definition(session, exclusivity_key=exclusive, per_account=5))
    with pytest.raises(OfferEligibilityError):
        redeem(session, ns, offer_definition(session, exclusivity_key=exclusive, per_account=5))


def test_redemption_identity_reuse_with_different_facts_conflicts(db):
    session = db.session
    ns = seed_account(session)
    other = seed_account(session)
    definition_id = offer_definition(session, per_account=3)
    redeem(session, ns, definition_id, redemption_id="same")
    with pytest.raises(OfferConflictError):
        redeem(session, ns, definition_id, redemption_id="same",
               actor={"actor_type": "system", "actor_id": "another-offer-service"})
    with pytest.raises(OfferConflictError):
        redeem(session, other, definition_id, redemption_id="same")


def test_replay_with_different_delivery_obligations_conflicts(db):
    session = db.session
    ns = seed_account(session)
    definition_id = offer_definition(session)
    redeem(session, ns, definition_id, redemption_id="r1")
    changed = ({**DELIVERIES[0], "channel": "other-channel"},)
    with pytest.raises(OfferConflictError):
        redeem(session, ns, definition_id, redemption_id="r1", deliveries=changed)


def test_failed_event_recording_rolls_back_every_effect(db):
    session = db.session
    ns = seed_account(session)
    definition_id = offer_definition(session)
    session.commit()
    before = _counts(session)
    with pytest.raises(OfferError):
        redeem(session, ns, definition_id, deliveries=[{"template_key": "x"}])
    session.rollback()
    assert _counts(session) == before
    assert session.query(IdempotencyRegistry).filter(
        IdempotencyRegistry.namespace == "credit_offer_redemption").count() == 0


def test_redemption_id_must_be_a_plain_identifier(db):
    session = db.session
    ns = seed_account(session)
    with pytest.raises(OfferError):
        redeem(session, ns, offer_definition(session), redemption_id="a:b")


def test_offer_terms_are_validated_at_redemption_time_only():
    definition = EntitlementDefinition(
        id="pure", key="pure", version=1, exclusivity_key="pure",
        capability_json={"schema_version": 1, "capabilities": {}},
        funding_policy_json={"schema_version": 1, "period_kind": "none", "credit_amount": 0},
        effective_at=ANCHOR, approved_at=ANCHOR, approval_evidence_reference="x",
    )
    with pytest.raises(OfferDependencyError):
        offer_terms(definition, AT)


# ---------------------------------------------------------------------------
# T-ADMIN / P08: admin authority, capability, data, and funding are separate
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("actor_type", ["user", "billing_owner", "global_admin", "admin", "organization_admin"])
def test_trials_and_promotions_are_redeemed_only_by_the_offer_service(db, actor_type):
    session = db.session
    ns = seed_account(session)
    before = _counts(session)
    with pytest.raises(OfferPermissionError):
        redeem(session, ns, offer_definition(session), actor={"actor_type": actor_type, "actor_id": ns.owner})
    assert _counts(session) == before


def test_comp_requires_explicit_permission_not_admin_or_billing_role(app, db):
    session = db.session
    ns = seed_account(session)
    definition_id = offer_definition(session, origin="comp", per_account=10)
    # A configured global admin who is also the customer's billing owner and
    # organization owner still has no comp authority.
    admin_id = ns.owner
    session.add(BillingRoleGrant(
        billing_account_id=ns.account, user_id=admin_id, role="billing_owner", starts_at=ANCHOR,
        origin_type="test", origin_id="test",
    ))
    session.flush()
    app.config["ADMIN_USER_IDS"] = admin_id
    try:
        actor = {
            "actor_type": "user", "actor_id": admin_id, "reason_code": "goodwill",
            "justification": "j", "evidence_reference": "ticket:1",
        }
        with pytest.raises(OfferPermissionError):
            redeem(session, ns, definition_id, actor=actor)
    finally:
        app.config.pop("ADMIN_USER_IDS", None)
    # The service actor cannot issue comps either.
    with pytest.raises(OfferPermissionError):
        redeem(session, ns, definition_id)
    # A permission for another command family does not transfer.
    internal_staff = staff(session, INTERNAL_PERMISSION)
    with pytest.raises(OfferPermissionError):
        redeem(session, ns, definition_id, actor=staff_actor(internal_staff))
    # Reason, justification, and evidence are mandatory.
    member = staff(session, COMP_PERMISSION)
    for missing in ("reason_code", "justification", "evidence_reference"):
        actor = staff_actor(member)
        actor[missing] = None
        with pytest.raises(OfferPermissionError):
            redeem(session, ns, definition_id, actor=actor)
    redemption, _fundings, lots, state = redeem(session, ns, definition_id, actor=staff_actor(member))
    assert state == "inserted"
    assert (redemption.origin, redemption.staff_permission_grant_id) == ("comp", member.grant)
    assert (redemption.actor_type, redemption.actor_id) == ("user", member.user)
    assert redemption.reason_code == "service_recovery" and redemption.evidence_reference == "ticket:test-1"
    assert lots[0].source_type == "comp"
    assert session.query(CreditLedgerEntry).filter_by(lot_id=lots[0].id).one().actor_id == member.user
    assert session.get(DomainEvent, redemption.domain_event_id).event_type == "comp_granted"


def test_revoked_or_out_of_interval_permission_authorizes_nothing(db):
    session = db.session
    ns = seed_account(session)
    definition_id = offer_definition(session, origin="comp", per_account=10)
    member = staff(session, COMP_PERMISSION)
    redeem(session, ns, definition_id, actor=staff_actor(member))
    revocation, state = revoke_staff_billing_permission(
        session, grant_id=member.grant, reason="role change", evidence_reference="hr:test", **PROVISIONER,
    )
    assert state == "inserted"
    assert abs(_utc(revocation.revoked_at) - datetime.now(timezone.utc)) < timedelta(minutes=5)
    with pytest.raises(OfferPermissionError):
        redeem(session, ns, definition_id, actor=staff_actor(member))
    again, state = revoke_staff_billing_permission(
        session, grant_id=member.grant, reason="role change", evidence_reference="hr:test", **PROVISIONER,
    )
    assert state == "duplicate" and again.id == revocation.id
    with pytest.raises(OfferConflictError):
        revoke_staff_billing_permission(
            session, grant_id=member.grant, reason="other", evidence_reference="hr:test", **PROVISIONER,
        )
    future = staff(session, COMP_PERMISSION, starts_at=datetime.now(timezone.utc) + timedelta(days=1))
    with pytest.raises(OfferPermissionError):
        redeem(session, ns, definition_id, actor=staff_actor(future))
    ended = staff(session, COMP_PERMISSION, starts_at=ANCHOR, ends_at=AT)
    with pytest.raises(OfferPermissionError):
        redeem(session, ns, definition_id, actor=staff_actor(ended))


def test_f1_callers_cannot_supply_or_backdate_command_time(db):
    """Audit F1: the original exploit passed an earlier ``redeemed_at`` to use an
    expired grant or a retired offer. No caller time is accepted any more."""
    session = db.session
    ns = seed_account(session)
    expired_grant = staff(session, COMP_PERMISSION, starts_at=ANCHOR, ends_at=AT)
    comp = offer_definition(session, origin="comp", per_account=10)
    retired = offer_definition(session, retired_at=AT + timedelta(days=1))
    before = _counts(session)
    for definition_id, actor in ((comp, staff_actor(expired_grant)), (retired, SYSTEM)):
        with pytest.raises(TypeError):
            redeem_credit_offer(
                session, billing_account_id=ns.account, entitlement_definition_id=definition_id,
                redemption_id="backdated", redeemed_at=AT, delivery_obligations=DELIVERIES, **actor,
            )
    with pytest.raises(OfferPermissionError):
        redeem(session, ns, comp, actor=staff_actor(expired_grant))
    with pytest.raises(OfferDependencyError, match="retired"):
        redeem(session, ns, retired)
    assert _counts(session) == before
    for command, extra in (
        (revoke_staff_billing_permission, {"grant_id": expired_grant.grant, "reason": "r",
                                           "evidence_reference": "e", "revoked_at": AT}),
        (expire_offer_entitlement, {"credit_offer_redemption_id": "x", "expired_at": AT}),
    ):
        with pytest.raises(TypeError):
            command(session, **extra, **PROVISIONER)


def test_retry_after_offer_retirement_returns_the_stored_result(db):
    session = db.session
    ns = seed_account(session)
    definition_id = offer_definition(session, per_account=5)
    redemption, *_ = redeem(session, ns, definition_id, redemption_id="before-retirement")
    definition = session.get(EntitlementDefinition, definition_id)
    definition.retired_at = db_now(session)  # ORM schema has no Phase 4 update guard
    session.flush()
    before = _counts(session)
    again, _fundings, _lots, state = redeem(session, ns, definition_id, redemption_id="before-retirement")
    assert (state, again.id) == ("duplicate", redemption.id) and _counts(session) == before
    with pytest.raises(OfferDependencyError):
        redeem(session, ns, definition_id, redemption_id="after-retirement")


def test_internal_funding_is_explicit_credit_not_plan_impersonation(db):
    session = db.session
    ns = seed_account(session)
    owner = session.get(User, ns.owner)
    plan_before = (owner.subscription_plan, owner.credits_remaining, session.get(Organization, ns.org).plan_key)
    definition_id = offer_definition(session, origin="internal", capabilities={}, days=90, per_account=4)
    member = staff(session, INTERNAL_PERMISSION)
    redemption, _fundings, lots, state = redeem(session, ns, definition_id, actor=staff_actor(member))
    assert state == "inserted" and redemption.entitlement_instance_id is None
    assert lots[0].source_type == "internal" and balance(session, lots[0].id) == (500, 0)
    assert session.get(DomainEvent, redemption.domain_event_id).event_type == "internal_funding_granted"
    session.refresh(owner)
    assert (owner.subscription_plan, owner.credits_remaining, session.get(Organization, ns.org).plan_key) == plan_before
    assert session.query(EntitlementInstance).filter_by(billing_account_id=ns.account).count() == 0


def test_staff_permissions_are_recorded_only_by_the_provisioning_service(db):
    session = db.session
    user_id = _user(session, uuid.uuid4().hex[:8], "staff")
    common = dict(
        grant_command_id="g-1", user_id=user_id, permission=COMP_PERMISSION, starts_at=ANCHOR, ends_at=None,
        approval_evidence_reference="founder-approval:test", justification="j",
    )
    for actor_type in ("user", "global_admin", "billing_owner"):
        with pytest.raises(OfferPermissionError):
            record_staff_billing_permission(session, actor_type=actor_type, actor_id=user_id, **common)
    with pytest.raises(OfferError):
        record_staff_billing_permission(session, **{**common, "permission": "billing.everything"}, **PROVISIONER)
    grant, state = record_staff_billing_permission(session, **common, **PROVISIONER)
    again, again_state = record_staff_billing_permission(session, **common, **PROVISIONER)
    assert (state, again_state, again.id) == ("inserted", "duplicate", grant.id)
    with pytest.raises(OfferConflictError):
        record_staff_billing_permission(session, **{**common, "justification": "other"}, **PROVISIONER)
    assert grant.permission_version == 1
    with pytest.raises(OfferPermissionError):
        revoke_staff_billing_permission(
            session, grant_id=grant.id, reason="r", evidence_reference="e",
            actor_type="user", actor_id=user_id,
        )


# ---------------------------------------------------------------------------
# Ownership, isolation, allocation order, and expiry (T-OWNER; D06)
# ---------------------------------------------------------------------------

def test_offer_value_stays_with_its_account_and_source(db):
    session = db.session
    first, second = seed_account(session), seed_account(session)
    definition_id = offer_definition(session, capabilities={})
    _r, _f, lots, _s = redeem(session, first, definition_id)
    assert {lot.billing_account_id for lot in lots} == {first.account}
    assert ordered_lot_balances(session, second.account, db_now(session) + timedelta(hours=1)) == []


def test_offer_lots_are_allocated_before_purchased_credit_and_stop_at_expiry(db):
    session = db.session
    ns = seed_account(session)
    purchase = pack_purchase(session, Ns(suffix=ns.suffix, account=ns.account), at=AT - timedelta(days=1))
    _r, _f, lots, _s = redeem(session, ns, offer_definition(session, capabilities={}, expiry="none"))
    now = db_now(session)
    order = [b.lot.source_type for b in ordered_lot_balances(session, ns.account, now + timedelta(hours=1))]
    # Phase 11 credit-pack policy: packs now expire at the paid term end. The
    # Phase 3 order is unchanged (expiry first, then source priority), so a
    # non-expiring trial now follows the expiring pack.
    assert order.index("credit_pack_purchase") < order.index("trial")
    _r, _f, expiring, _s = redeem(session, ns, offer_definition(session, capabilities={}, days=7))
    after_end = _utc(expiring[0].expires_at) + timedelta(seconds=1)
    available = {b.lot.id for b in ordered_lot_balances(session, ns.account, after_end)}
    assert expiring[0].id not in available and lots[0].id in available
    assert set(purchase.lots.values()) <= available


def test_offer_entitlement_expires_only_after_its_term(db, monkeypatch):
    import app.billing_offers as offers

    session = db.session
    ns = seed_account(session)
    redemption, *_ = redeem(session, ns, offer_definition(session, days=3))
    term_end = _utc(redemption.term_ends_at)
    # Before the term ends (real database time) expiry is refused.
    with pytest.raises(OfferError, match="has not ended"):
        expire_offer_entitlement(session, credit_offer_redemption_id=redemption.id, **SYSTEM)
    with pytest.raises(OfferPermissionError):
        expire_offer_entitlement(session, credit_offer_redemption_id=redemption.id,
                                 actor_type="user", actor_id=ns.owner)
    # Advance only the test clock (the ORM schema has no database guard).
    monkeypatch.setattr(offers, "_database_now", lambda _session: term_end + timedelta(seconds=1))
    instance, state = expire_offer_entitlement(session, credit_offer_redemption_id=redemption.id, **SYSTEM)
    assert (state, instance.state) == ("inserted", "expired")
    expired_event = session.get(EntitlementEvent, instance.last_event_id)
    assert _utc(expired_event.effective_at) == term_end
    _instance, state = expire_offer_entitlement(session, credit_offer_redemption_id=redemption.id, **SYSTEM)
    assert state == "duplicate"


def test_phase10_service_has_no_live_runtime_callers():
    app_dir = BACKEND_DIR / "app"
    callers = [
        str(path.relative_to(BACKEND_DIR))
        for path in app_dir.rglob("*.py")
        # Phase 11 contract administration and the Phase 14 backfill are inactive and reuse Phase 10 grants.
        if path.name not in {"billing_offers.py", "billing_enterprise_contracts.py", "models_billing_phase10.py", "models.py",
                             "billing_migration.py"}
        and ("billing_offers" in path.read_text() or "models_billing_phase10" in path.read_text())
    ]
    assert callers == []


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

_MODULE = {}


def _revision():
    if "module" not in _MODULE:
        _MODULE["module"] = ScriptDirectory(MIGRATIONS_DIR).get_revision(REVISION).module
    return _MODULE["module"]


@contextlib.contextmanager
def _ops(engine):
    with engine.begin() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            yield connection


def _predecessor(engine):
    # Phase 11 tables are later than this revision and refer to its tables.
    phase11 = ("enterprise_contracts", "enterprise_contract_versions", "enterprise_contract_events", "enterprise_contract_term_fundings", "enterprise_contract_activations", "enterprise_contract_notices")
    # Phase 14 migration reviews also refer to Phase 10 staff grants.
    phase14 = ("billing_migration_plan_mappings", "billing_migration_payment_archives",
               "billing_migration_openings", "billing_migration_reviews", "billing_migration_account_results",
               "billing_migration_payment_attributions", "billing_migration_payer_bindings",
               "billing_migration_establishments", "billing_migration_runs",
               "billing_migration_operation_decisions")  # BI-1 decisions refer to them too
    tables = [t for t in flask_db.metadata.sorted_tables if t.name not in PHASE10_TABLES + phase11 + phase14]
    flask_db.metadata.create_all(engine, tables=tables)
    # The models now carry the Phase 11 constraint texts; restore the Phase 10
    # forms so this revision sees its exact predecessor schema.
    phase11 = ScriptDirectory(MIGRATIONS_DIR).get_revision("b4d6f8a0c2e5").module
    with _ops(engine) as connection:
        for table, name, old, new in phase11.CHECKS:
            if table == "billing_staff_permission_grants":
                continue
            if engine.dialect.name == "postgresql":
                connection.execute(sa.text(f"ALTER TABLE {table} DROP CONSTRAINT {name}"))
                connection.execute(sa.text(f"ALTER TABLE {table} ADD CONSTRAINT {name} CHECK ({old})"))
            else:
                phase11._sqlite_replace_check(table, new, old)


def _assert_models_match(engine):
    from app.models_billing_phase10 import (
        BillingStaffPermissionGrant as Grant, BillingStaffPermissionRevocation as Revocation,
        CreditOfferFunding as Funding, CreditOfferRedemption as Redemption,
    )
    inspector = sa.inspect(engine)
    for model in (Grant, Revocation, Redemption, Funding):
        table = model.__table__
        assert {c.name for c in table.columns} == {c["name"] for c in inspector.get_columns(table.name)}
        model_names = {c.name for c in table.constraints if c.name} - {table.primary_key.name}
        db_names = {
            c["name"] for c in (
                inspector.get_check_constraints(table.name) + inspector.get_foreign_keys(table.name)
                + inspector.get_unique_constraints(table.name)
            ) if c.get("name")
        }
        assert model_names == db_names, table.name
        assert {i.name for i in table.indexes} <= {i["name"] for i in inspector.get_indexes(table.name)}


def _gate_sql(connection):
    return connection.execute(sa.text(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='entitlement_instances'"
    )).scalar_one()


def test_revision_extends_phase9_and_is_single_head():
    script = ScriptDirectory(MIGRATIONS_DIR)
    assert script.get_heads() == ["a1f3c5e7b9d0"]  # I1 follows BI-1; BI-1 extends the Phase 17 guard, which extends Phase 14 without changing Phase 10.
    assert script.get_revision(REVISION).down_revision == PARENT


def test_sqlite_migration_matches_models_regates_and_downgrade_is_safe(tmp_path):
    module = _revision()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase10.sqlite'}")

    @sa.event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    try:
        _predecessor(engine)
        with _ops(engine) as connection:
            # Recreate the exact Phase 9 schema: the model now carries the
            # Phase 10 gate, so restore the Phase 4 text before upgrading.
            module._sqlite_replace_gate(module.NEW_GATE, module.OLD_GATE)
            assert module.OLD_GATE in _gate_sql(connection)
            # Stand-ins for the Phase 4 triggers: one on the rebuilt table and
            # one on another table that refers to it by name.
            connection.execute(sa.text(
                "CREATE TRIGGER trg_test_own BEFORE DELETE ON entitlement_instances "
                "BEGIN SELECT RAISE(ABORT,'own-table marker'); END"
            ))
            connection.execute(sa.text(
                "CREATE TRIGGER trg_test_cross BEFORE INSERT ON entitlement_events WHEN NOT EXISTS ("
                "SELECT 1 FROM entitlement_instances i WHERE i.id=NEW.entitlement_instance_id) "
                "BEGIN SELECT RAISE(ABORT,'cross-table marker'); END"
            ))
        with _ops(engine):
            module.upgrade()
        _assert_models_match(engine)
        with engine.connect() as connection:
            sql = _gate_sql(connection)
            assert module.NEW_GATE in sql and module.OLD_GATE not in sql
            names = set(connection.execute(sa.text(
                "SELECT name FROM sqlite_master WHERE type IN ('trigger','index') "
                "AND tbl_name='entitlement_instances'"
            )).scalars())
            assert {"trg_test_own", "ix_entitlement_instances_account_state_interval",
                    "ix_entitlement_instances_definition_id"} <= names
            with pytest.raises(sa.exc.DBAPIError, match="cross-table marker"):
                connection.execute(sa.text(
                    "INSERT INTO entitlement_events (id,entitlement_instance_id,transition,from_state,to_state,"
                    "effective_at,created_at,actor_type,actor_id,source_type,source_id,idempotency_registry_id,"
                    "evidence_json) VALUES ('e1','missing','t','proposed','scheduled','2026-02-01','2026-02-01',"
                    "'system','x','test','x','r1','{}')"
                ))
            connection.rollback()
            triggers = set(connection.execute(sa.text(
                "SELECT name FROM sqlite_master WHERE type='trigger' AND name LIKE 'trg_phase10_%'"
            )).scalars())
            assert triggers == set(module.SQLITE_TRIGGERS)
        with _ops(engine):
            module.downgrade()
        with engine.connect() as connection:
            assert module.OLD_GATE in _gate_sql(connection)
            assert "trg_test_own" in set(connection.execute(sa.text(
                "SELECT name FROM sqlite_master WHERE type='trigger'")).scalars())
        assert not set(sa.inspect(engine).get_table_names()) & set(PHASE10_TABLES)
        with _ops(engine):
            module.upgrade()
        with engine.begin() as connection:
            connection.execute(sa.text("PRAGMA foreign_keys=OFF"))
            with pytest.raises(sa.exc.DBAPIError):
                connection.execute(sa.text(
                    "INSERT INTO credit_lots (id,billing_account_id,source_type,source_id,original_amount,"
                    "available_at,origin_evidence_json,created_at) VALUES "
                    "('lot-x','a','comp','none',10,'2026-01-31','{}','2026-01-31')"
                ))
            connection.execute(sa.text(
                "INSERT INTO billing_staff_permission_grants (id,user_id,permission,permission_version,"
                "starts_at,grant_key,request_fingerprint,approval_evidence_reference,justification,"
                "idempotency_registry_id,actor_type,actor_id,created_at) VALUES "
                "('g1','u1','billing.comp.grant',1,'2026-01-31','staff-permission:g1',:fp,'e','j','r1',"
                "'system','x','2026-01-31')"
            ), {"fp": "a" * 64})
            for statement in (
                "UPDATE billing_staff_permission_grants SET justification='changed'",
                "DELETE FROM billing_staff_permission_grants",
            ):
                with pytest.raises(sa.exc.DBAPIError):
                    connection.execute(sa.text(statement))
        with pytest.raises(module.Phase10EvidenceNotEmptyError):
            with _ops(engine):
                module.downgrade()
        assert "billing_staff_permission_grants" in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()


def test_sqlite_gate_rebuild_preserves_populated_rows_under_foreign_keys(tmp_path):
    module = _revision()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase10-populated.sqlite'}")

    @sa.event.listens_for(engine, "connect")
    def _fk_on(dbapi_connection, _record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    try:
        _predecessor(engine)
        with _ops(engine):
            module._sqlite_replace_gate(module.NEW_GATE, module.OLD_GATE)
        with engine.begin() as connection:
            connection.execute(sa.text("PRAGMA foreign_keys=OFF"))
            connection.execute(sa.text(
                "INSERT INTO entitlement_definitions (id,key,version,exclusivity_key,capability_json,"
                "funding_policy_json,created_at) VALUES ('d1','k',1,'k','{}','{}','2026-01-01')"
            ))
            connection.execute(sa.text(
                "INSERT INTO billing_accounts (id,organization_id,status,currency,account_anchor_at,"
                "created_at,updated_at) VALUES ('a1','o1','active','usd','2026-01-01','2026-01-01','2026-01-01')"
            ))
            for instance_id, supersedes in (("i1", None), ("i2", "i1")):
                connection.execute(sa.text(
                    "INSERT INTO entitlement_instances (id,billing_account_id,entitlement_definition_id,state,"
                    "starts_at,source_type,source_id,supersedes_instance_id,created_at,updated_at) VALUES "
                    "(:id,'a1','d1','proposed','2026-02-01','free',:id,:sup,'2026-01-01','2026-01-01')"
                ), {"id": instance_id, "sup": supersedes})
            connection.execute(sa.text(
                "INSERT INTO credit_periods (id,billing_account_id,entitlement_instance_id,kind,period_index,"
                "anchor_at,starts_at,ends_at,planned_allocation_amount,state,created_at,updated_at) VALUES "
                "('p1','a1','i1','free',0,'2026-02-01','2026-02-01','2026-03-01',1,'planned','2026-01-01',"
                "'2026-01-01')"
            ))
        engine.dispose()  # new pooled connections re-enable foreign keys
        with engine.connect() as connection:
            assert connection.execute(sa.text("PRAGMA foreign_keys")).scalar() == 1
        with _ops(engine):
            module.upgrade()
        with engine.connect() as connection:
            rows = connection.execute(sa.text(
                "SELECT id, supersedes_instance_id FROM entitlement_instances ORDER BY id")).all()
            assert [tuple(row) for row in rows] == [("i1", None), ("i2", "i1")]
            assert connection.execute(sa.text("PRAGMA foreign_key_check(entitlement_instances)")).all() == []
            assert connection.execute(sa.text("PRAGMA foreign_key_check(credit_periods)")).all() == []
            assert connection.execute(sa.text("PRAGMA foreign_keys")).scalar() == 1
        # The rewritten CHECK is enforced, not just stored: trials may now leave
        # proposed (the Phase 10 guard decides), enterprise contracts may not.
        with engine.begin() as connection:
            connection.execute(sa.text("UPDATE entitlement_instances SET source_type='trial', state='active', approval_evidence_reference='approval:test' WHERE id='i2'"))
            with pytest.raises(sa.exc.IntegrityError):
                connection.execute(sa.text(
                    "UPDATE entitlement_instances SET source_type='enterprise_contract' WHERE id='i2'"))
        with engine.begin() as connection:
            connection.execute(sa.text("UPDATE entitlement_instances SET state='proposed' WHERE id='i2'"))
        with _ops(engine):
            module.downgrade()
        with engine.connect() as connection:
            assert connection.execute(sa.text("SELECT count(*) FROM entitlement_instances")).scalar() == 2
            assert module.OLD_GATE in _gate_sql(connection)
        with engine.begin() as connection:
            with pytest.raises(sa.exc.IntegrityError):
                connection.execute(sa.text("UPDATE entitlement_instances SET state='active' WHERE id='i2'"))
    finally:
        engine.dispose()


def test_sqlite_migrated_offer_entitlement_needs_redemption_evidence(tmp_path):
    module = _revision()
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase10-gate.sqlite'}")
    try:
        _predecessor(engine)
        with _ops(engine):
            module._sqlite_replace_gate(module.NEW_GATE, module.OLD_GATE)
        with _ops(engine):
            module.upgrade()
        with engine.begin() as connection:
            connection.execute(sa.text("PRAGMA foreign_keys=OFF"))
            connection.execute(sa.text(
                "INSERT INTO entitlement_definitions (id,key,version,exclusivity_key,capability_json,"
                "funding_policy_json,effective_at,approved_at,approval_evidence_reference,created_at) VALUES "
                "('d1','k',1,'k','{}','{}','2026-01-01','2026-01-01','approval:test','2026-01-01')"
            ))
            connection.execute(sa.text(
                "INSERT INTO entitlement_instances (id,billing_account_id,entitlement_definition_id,state,"
                "starts_at,ends_at,source_type,source_id,approval_evidence_reference,created_at,updated_at) "
                "VALUES ('i1','a1','d1','proposed','2026-02-01','2026-03-01','promotion','forged',"
                "'approval:test','2026-01-01','2026-01-01')"
            ))
            connection.execute(sa.text(
                "INSERT INTO idempotency_registry (id,namespace,key,request_fingerprint,state,claimed_at) "
                "VALUES ('r1','test','k1',:fp,'claimed','2026-01-01')"
            ), {"fp": "b" * 64})
            with pytest.raises(sa.exc.DBAPIError, match="redemption evidence"):
                connection.execute(sa.text(
                    "INSERT INTO entitlement_events (id,entitlement_instance_id,transition,from_state,to_state,"
                    "effective_at,created_at,actor_type,actor_id,source_type,source_id,idempotency_registry_id,"
                    "evidence_json) VALUES ('e1','i1','forged','proposed','scheduled','2026-02-01','2026-02-01',"
                    "'system','x','test','x','r1','{}')"
                ))
    finally:
        engine.dispose()


@pytest.mark.postgres
@PG
def test_postgres_isolated_migration_guards_and_downgrade_safety(validate_test_database_url, postgres_schema_url):
    module = _revision()
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase10_{uuid.uuid4().hex}"
    admin = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = sa.create_engine(postgres_schema_url(base_url, schema))

    def gate(connection):
        return connection.execute(sa.text(
            "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c JOIN pg_namespace n ON n.oid=c.connamespace "
            "WHERE n.nspname=current_schema() AND c.conname=:name"
        ), {"name": module.GATE_NAME}).scalar_one()

    try:
        _predecessor(engine)
        with _ops(engine) as connection:
            connection.execute(sa.text(f"ALTER TABLE entitlement_instances DROP CONSTRAINT {module.GATE_NAME}"))
            connection.execute(sa.text(
                f"ALTER TABLE entitlement_instances ADD CONSTRAINT {module.GATE_NAME} CHECK ({module.OLD_GATE})"
            ))
        with _ops(engine):
            module.upgrade()
        _assert_models_match(engine)
        with engine.connect() as connection:
            assert "enterprise_contract" in gate(connection) and "trial" not in gate(connection)
            triggers = set(connection.execute(sa.text(
                "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE NOT t.tgisinternal AND n.nspname=current_schema() AND t.tgname LIKE 'trg_phase10_%'"
            )).scalars())
        assert triggers == {name for name, _table in module.PG_TRIGGERS}
        with _ops(engine):
            module.downgrade()
        with engine.connect() as connection:
            leftover = connection.execute(sa.text(
                "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname=current_schema() AND p.proname LIKE 'phase10_%'"
            )).scalar_one()
            assert leftover == 0 and "trial" in gate(connection)
        with _ops(engine):
            module.upgrade()
        with engine.connect() as connection:
            with pytest.raises(sa.exc.DBAPIError):
                connection.execute(sa.text("TRUNCATE credit_offer_redemptions"))
            connection.rollback()
            connection.execute(sa.text("SET session_replication_role = replica"))
            connection.execute(sa.text(
                "INSERT INTO billing_staff_permission_revocations (id,grant_id,revoked_at,reason,"
                "evidence_reference,actor_type,actor_id) VALUES ('v1','g','2026-01-01','r','e','system','x')"
            ))
            connection.commit()
        with pytest.raises(module.Phase10EvidenceNotEmptyError):
            with _ops(engine):
                module.downgrade()
    finally:
        engine.dispose()
        with admin.connect() as connection:
            connection.execute(sa.text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
        admin.dispose()


# ---------------------------------------------------------------------------
# Fully migrated PostgreSQL: guarded service paths, bypass rejection, races
# ---------------------------------------------------------------------------

def _migrated_engine():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("local disposable PostgreSQL is not configured")
    engine = sa.create_engine(url, pool_size=10, max_overflow=4)
    with engine.connect() as connection:
        revision = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    if revision not in {REVISION, "b4d6f8a0c2e5", "c8e0a2b4d6f1", "d2f4a6c8e0b3", "f3a5c7e9b1d2", "c8a9989843b5", "a1f3c5e7b9d0"}:
        engine.dispose()
        pytest.fail(f"Phase 10 migrated tests require Alembic head {REVISION} or Phase 11; found {revision!r}")
    return engine


@pytest.mark.postgres
@PG
def test_postgres_migrated_lifecycle_passes_every_guard():
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed_account(session)
            trial = offer_definition(session, days=5)
            promo = offer_definition(session, origin="promotion", capabilities={}, expiry="none",
                                     components=[{"component": "a", "credit_amount": 10},
                                                 {"component": "b", "credit_amount": 20}])
            comp = offer_definition(session, origin="comp", capabilities={})
            internal = offer_definition(session, origin="internal", capabilities={})
            comp_staff = staff(session, COMP_PERMISSION)
            internal_staff = staff(session, INTERNAL_PERMISSION)
            session.commit()
            redemption, *_ = redeem(session, ns, trial, redemption_id="t1")
            session.commit()
            assert redeem(session, ns, trial, redemption_id="t1")[3] == "duplicate"
            session.commit()
            redeem(session, ns, promo)
            session.commit()
            redeem(session, ns, comp, actor=staff_actor(comp_staff))
            session.commit()
            _r, _f, lots, _s = redeem(session, ns, internal, actor=staff_actor(internal_staff))
            session.commit()
            assert balance(session, lots[0].id) == (500, 0)
            # Database time decides expiry: the five-day term has not ended.
            with pytest.raises(OfferError, match="has not ended"):
                expire_offer_entitlement(session, credit_offer_redemption_id=redemption.id, **SYSTEM)
            session.rollback()
            assert session.query(CreditOfferRedemption).filter_by(billing_account_id=ns.account).count() == 4
    finally:
        engine.dispose()


def _raises_integrity(session, statement, params=None):
    with pytest.raises(sa.exc.DBAPIError):
        session.execute(sa.text(statement), params or {})
        session.commit()
    session.rollback()


@pytest.mark.postgres
@PG
def test_postgres_migrated_guards_reject_direct_bypass():
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed_account(session)
            trial = offer_definition(session)
            comp = offer_definition(session, origin="comp", capabilities={}, per_account=5)
            member = staff(session, COMP_PERMISSION)
            session.commit()
            redemption, fundings, lots, _s = redeem(session, ns, trial)
            session.commit()

            def claim(namespace, key):
                rid = str(uuid.uuid4())
                session.execute(sa.text(
                    "INSERT INTO idempotency_registry (id,namespace,key,request_fingerprint,state,claimed_at) "
                    "VALUES (:id,:ns,:key,:fp,'claimed',now())"
                ), {"id": rid, "ns": namespace, "key": key, "fp": "e" * 64})
                return rid

            # Offer-sourced value cannot be minted without Phase 10 funding evidence.
            for source in ("trial", "promotional", "comp", "internal"):
                _raises_integrity(session, (
                    "INSERT INTO credit_lots (id,billing_account_id,source_type,source_id,original_amount,"
                    "available_at,origin_evidence_json) VALUES (:id,:a,:s,'x',100,now(),'{}')"
                ), {"id": str(uuid.uuid4()), "a": ns.account, "s": source})
            # A second grant on an offer lot is refused even when consumption
            # left room under the original amount (isolates the grant guard
            # from the Phase 3 original-amount cap).
            consume(session, ns.account, lots[0].id, 100)
            session.commit()
            rid = claim("test", str(uuid.uuid4()))
            _raises_integrity(session, (
                "INSERT INTO credit_ledger_entries (id,billing_account_id,lot_id,entry_type,available_delta,"
                "held_delta,idempotency_registry_id,effective_at,actor_type,actor_id,reason_code,evidence_json) "
                "VALUES (:id,:a,:lot,'grant',1,0,:r,now(),'system','x','bypass','{}')"
            ), {"id": str(uuid.uuid4()), "a": ns.account, "lot": lots[0].id, "r": rid})
            # A promotion or comp entitlement cannot be activated without a redemption.
            definition = session.get(EntitlementDefinition, trial)
            for source in ("promotion", "comp", "trial", "internal"):
                instance_id = str(uuid.uuid4())
                session.execute(sa.text(
                    "INSERT INTO entitlement_instances (id,billing_account_id,entitlement_definition_id,state,"
                    "starts_at,ends_at,source_type,source_id,approval_evidence_reference) VALUES "
                    "(:id,:a,:d,'proposed',:s,:e,:src,:id,'approval:forged')"
                ), {"id": instance_id, "a": ns.account, "d": definition.id, "s": AT + timedelta(days=400),
                    "e": AT + timedelta(days=401), "src": source})
                rid = claim("test", str(uuid.uuid4()))
                _raises_integrity(session, (
                    "INSERT INTO entitlement_events (id,entitlement_instance_id,transition,from_state,to_state,"
                    "effective_at,actor_type,actor_id,source_type,source_id,idempotency_registry_id,evidence_json) "
                    "VALUES (:id,:i,'forged','proposed','scheduled',now(),'system','x','test','x',:r,'{}')"
                ), {"id": str(uuid.uuid4()), "i": instance_id, "r": rid})
            # Enterprise contracts stay gated until Phase 11.
            _raises_integrity(session, (
                "INSERT INTO entitlement_instances (id,billing_account_id,entitlement_definition_id,state,"
                "starts_at,source_type,source_id,approval_evidence_reference) VALUES "
                "(:id,:a,:d,'active',now(),'enterprise_contract','x','approval:x')"
            ), {"id": str(uuid.uuid4()), "a": ns.account, "d": definition.id})
            # Evidence is immutable and cannot be truncated.
            _raises_integrity(session, "UPDATE credit_offer_redemptions SET credit_amount=1 WHERE id=:id",
                              {"id": redemption.id})
            _raises_integrity(session, "DELETE FROM credit_offer_fundings WHERE id=:id", {"id": fundings[0].id})
            _raises_integrity(session, "UPDATE billing_staff_permission_grants SET ends_at=now()")
            _raises_integrity(session, "TRUNCATE billing_staff_permission_grants")
            # A revoked grant cannot back a comp redemption inserted directly.
            revoke_staff_billing_permission(
                session, grant_id=member.grant, reason="r", evidence_reference="e", **PROVISIONER,
            )
            session.commit()
            with pytest.raises(OfferPermissionError):
                redeem(session, ns, comp, actor=staff_actor(member))
            session.rollback()
            # A forged capabilities-only comp redemption backed by the revoked
            # grant passes every CHECK and the deferred completeness trigger
            # (no components), so only the redemption guard can refuse it.
            capability_comp = offer_definition(session, origin="comp", components=[], per_account=5)
            session.commit()
            definition = session.get(EntitlementDefinition, capability_comp)
            key = f"offer-redemption:{capability_comp}:forged"
            rid = claim("credit_offer_redemption", key)
            _raises_integrity(session, (
                "INSERT INTO credit_offer_redemptions (id,billing_account_id,entitlement_definition_id,offer_key,"
                "offer_version,origin,redemption_id,redemption_key,request_fingerprint,funding_source,redeemed_at,"
                "term_starts_at,term_ends_at,credit_amount,per_account_limit,total_limit,account_redemption_index,"
                "total_redemption_index,staff_permission_grant_id,reason_code,justification,evidence_reference,"
                "idempotency_registry_id,domain_event_id,contract_version,actor_type,actor_id) VALUES "
                "(:id,:a,:d,:k,1,'comp','forged',:key,:fp,'jaspen_test_budget',:at,:at,:end,0,5,1000,1,1,:g,"
                "'r','j','e',:r,:ev,1,'user',:u)"
            ), {"id": str(uuid.uuid4()), "a": ns.account, "d": capability_comp, "k": definition.key, "key": key,
                "fp": "f" * 64, "at": AT, "end": AT + timedelta(days=14), "g": member.grant, "r": rid,
                "ev": redemption.domain_event_id, "u": member.user})
    finally:
        engine.dispose()


ISOLATION_LEVELS = ("READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE")


@pytest.mark.postgres
@PG
@pytest.mark.parametrize("isolation_level", ISOLATION_LEVELS)
def test_postgres_concurrent_redemptions_respect_limits_and_converge(isolation_level):
    engine = _migrated_engine()
    racing = engine.execution_options(isolation_level=isolation_level)
    try:
        with Session(engine, expire_on_commit=False) as session:
            accounts = [seed_account(session) for _ in range(4)]
            limited = offer_definition(session, capabilities={}, total=2)
            replayed = offer_definition(session, capabilities={})
            session.commit()

        def attempt(ns, definition_id, redemption_id, barrier):
            for count in range(8):
                with Session(racing) as session:
                    try:
                        if count == 0:
                            barrier.wait()
                        state = redeem(session, ns, definition_id, redemption_id=redemption_id)[3]
                        session.commit()
                        return state
                    except OfferLimitError:
                        session.rollback()
                        return "limit"
                    except OfferIsolationError:
                        session.rollback()
                        return "isolation"
                    except (sa.exc.DBAPIError, OfferRetryError):
                        session.rollback()
            return "gave-up"

        barrier = threading.Barrier(4)
        with ThreadPoolExecutor(max_workers=4) as pool:
            limit_results = list(pool.map(
                lambda ns: attempt(ns, limited, f"race-{ns.suffix}", barrier), accounts,
            ))
        barrier = threading.Barrier(3)
        with ThreadPoolExecutor(max_workers=3) as pool:
            replay_results = list(pool.map(
                lambda _i: attempt(accounts[0], replayed, "same-signup", barrier), range(3),
            ))
        with Session(engine) as session:
            limited_rows = session.query(CreditOfferRedemption).filter_by(entitlement_definition_id=limited).count()
            replayed_rows = session.query(CreditOfferRedemption).filter_by(entitlement_definition_id=replayed).count()
        if isolation_level == "READ COMMITTED":
            assert sorted(limit_results) == ["inserted", "inserted", "limit", "limit"]
            assert sorted(replay_results) == ["duplicate", "duplicate", "inserted"]
            assert (limited_rows, replayed_rows) == (2, 1)
        else:
            # Audit F2: authorization-bearing redemptions refuse snapshot isolation.
            assert set(limit_results) == {"isolation"} and set(replay_results) == {"isolation"}
            assert (limited_rows, replayed_rows) == (0, 0)
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Audit remediation regressions (F1 database time, F2 revocation race, F3 scope)
# ---------------------------------------------------------------------------

def _redemption_effects(session, account_id):
    return (
        session.query(CreditOfferRedemption).filter_by(billing_account_id=account_id).count(),
        session.query(CreditLot).filter_by(billing_account_id=account_id).count(),
        session.query(EntitlementInstance).filter_by(billing_account_id=account_id).count(),
        session.query(DomainEvent).filter_by(billing_account_id=account_id).count(),
    )


@pytest.mark.postgres
@PG
def test_postgres_f1_database_rejects_caller_supplied_times():
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed_account(session)
            definition_id = offer_definition(session, capabilities={})
            member = staff(session, COMP_PERMISSION)
            session.commit()
            redemption, *_ = redeem(session, ns, definition_id)
            session.commit()
            db_time = session.execute(sa.text("SELECT now()")).scalar_one()
            session.rollback()
            assert _utc(redemption.redeemed_at) <= _utc(db_time)
            # A backdated revocation inserted directly is refused.
            _raises_integrity(session, (
                "INSERT INTO billing_staff_permission_revocations (id,grant_id,revoked_at,reason,"
                "evidence_reference,actor_type,actor_id) VALUES (:id,:g,:t,'r','e','system','x')"
            ), {"id": str(uuid.uuid4()), "g": member.grant, "t": AT})
            # A redemption row claiming an earlier time is refused before any other check.
            with pytest.raises(sa.exc.DBAPIError, match="database time"):
                session.execute(sa.text(
                    "INSERT INTO credit_offer_redemptions (id,billing_account_id,entitlement_definition_id,"
                    "offer_key,offer_version,origin,redemption_id,redemption_key,request_fingerprint,funding_source,"
                    "redeemed_at,term_starts_at,term_ends_at,credit_amount,per_account_limit,total_limit,"
                    "account_redemption_index,total_redemption_index,idempotency_registry_id,domain_event_id,"
                    "contract_version,actor_type,actor_id) SELECT :id,r.billing_account_id,"
                    "r.entitlement_definition_id,r.offer_key,r.offer_version,r.origin,'backdated',"
                    "'offer-redemption:' || r.entitlement_definition_id || :suffix,r.request_fingerprint,"
                    "r.funding_source,:t,:t,:t + interval '14 days',r.credit_amount,r.per_account_limit,"
                    "r.total_limit,2,2,r.idempotency_registry_id,r.domain_event_id,1,'system','x' "
                    "FROM credit_offer_redemptions r WHERE r.id=:rid"
                ), {"id": str(uuid.uuid4()), "t": AT, "rid": redemption.id, "suffix": ":backdated"})
            session.rollback()
    finally:
        engine.dispose()


def _begin_snapshot(engine, isolation_level):
    """Open a transaction at ``isolation_level`` and take its snapshot now."""
    session = Session(engine.execution_options(isolation_level=isolation_level), expire_on_commit=False)
    session.execute(sa.text("SELECT 1"))
    return session


@pytest.mark.postgres
@PG
@pytest.mark.parametrize("isolation_level", ISOLATION_LEVELS)
def test_postgres_f2_revocation_committed_during_a_redemption_wins(isolation_level):
    """The audit reproduction: the redemption's transaction (and snapshot)
    starts, the revocation commits, then the redemption authorizes."""
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed_account(session)
            definition_id = offer_definition(session, origin="comp", capabilities={}, per_account=10)
            member = staff(session, COMP_PERMISSION)
            session.commit()
            before = _redemption_effects(session, ns.account)
        redeeming = _begin_snapshot(engine, isolation_level)
        try:
            with Session(engine) as revoking:
                revoke_staff_billing_permission(
                    revoking, grant_id=member.grant, reason="revoked mid-flight", evidence_reference="e",
                    **PROVISIONER,
                )
                revoking.commit()
            expected = OfferPermissionError if isolation_level == "READ COMMITTED" else OfferIsolationError
            with pytest.raises(expected):
                redeem(redeeming, ns, definition_id, actor=staff_actor(member))
            redeeming.rollback()
        finally:
            redeeming.close()
        with Session(engine) as session:
            assert _redemption_effects(session, ns.account) == before
    finally:
        engine.dispose()


@pytest.mark.postgres
@PG
@pytest.mark.parametrize("isolation_level", ISOLATION_LEVELS)
def test_postgres_f2_database_refuses_snapshot_isolation_writes(isolation_level):
    """Without the service, the guards still refuse REPEATABLE READ and SERIALIZABLE."""
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            member = staff(session, COMP_PERMISSION)
            session.commit()
        writer = _begin_snapshot(engine, isolation_level)
        try:
            statement = sa.text(
                "INSERT INTO billing_staff_permission_revocations (id,grant_id,revoked_at,reason,"
                "evidence_reference,actor_type,actor_id) VALUES (:id,:g,now(),'r','e','system','x')"
            )
            params = {"id": str(uuid.uuid4()), "g": member.grant}
            if isolation_level == "READ COMMITTED":
                writer.execute(statement, params)
                writer.rollback()
            else:
                with pytest.raises(sa.exc.DBAPIError, match="READ COMMITTED"):
                    writer.execute(statement, params)
                writer.rollback()
                with pytest.raises(OfferIsolationError):
                    revoke_staff_billing_permission(
                        writer, grant_id=member.grant, reason="r", evidence_reference="e", **PROVISIONER,
                    )
                writer.rollback()
        finally:
            writer.close()
    finally:
        engine.dispose()


@pytest.mark.postgres
@PG
def test_postgres_f2_concurrent_revocation_and_redemption_have_one_valid_order():
    engine = _migrated_engine()
    try:
        for _round in range(5):
            with Session(engine, expire_on_commit=False) as session:
                ns = seed_account(session)
                definition_id = offer_definition(session, origin="comp", capabilities={}, per_account=10)
                member = staff(session, COMP_PERMISSION)
                session.commit()
            barrier = threading.Barrier(2)
            order = []
            lock = threading.Lock()

            def redeem_once():
                with Session(engine) as session:
                    barrier.wait()
                    try:
                        redeem(session, ns, definition_id, actor=staff_actor(member))
                        session.commit()
                        with lock:
                            order.append("redeemed")
                        return "redeemed"
                    except OfferPermissionError:
                        session.rollback()
                        return "refused"

            def revoke_once():
                with Session(engine) as session:
                    barrier.wait()
                    revoke_staff_billing_permission(
                        session, grant_id=member.grant, reason="race", evidence_reference="e", **PROVISIONER,
                    )
                    session.commit()
                    with lock:
                        order.append("revoked")
                    return "revoked"

            with ThreadPoolExecutor(max_workers=2) as pool:
                outcome = pool.submit(redeem_once), pool.submit(revoke_once)
                redeemed, revoked = outcome[0].result(), outcome[1].result()
            assert revoked == "revoked" and redeemed in {"redeemed", "refused"}
            with Session(engine) as session:
                rows = session.query(CreditOfferRedemption).filter_by(billing_account_id=ns.account).all()
                revocation = session.query(BillingStaffPermissionRevocation).filter_by(grant_id=member.grant).one()
                if redeemed == "redeemed":
                    # The redemption held the grant lock first, so it is ordered
                    # before the revocation, and its database time precedes it.
                    assert len(rows) == 1 and order == ["redeemed", "revoked"]
                    assert _utc(rows[0].redeemed_at) < _utc(revocation.revoked_at)
                else:
                    assert rows == [] and session.query(CreditLot).filter_by(billing_account_id=ns.account).count() == 0
            # After the revocation commits, the grant authorizes nothing.
            with Session(engine) as session:
                with pytest.raises(OfferPermissionError):
                    redeem(session, ns, definition_id, actor=staff_actor(member))
                session.rollback()
    finally:
        engine.dispose()


def _transition(session, instance_id, from_state, to_state, effective_at):
    registry_id = str(uuid.uuid4())
    session.execute(sa.text(
        "INSERT INTO idempotency_registry (id,namespace,key,request_fingerprint,state,claimed_at) "
        "VALUES (:id,'test_transition',:key,:fp,'claimed',now())"
    ), {"id": registry_id, "key": str(uuid.uuid4()), "fp": "d" * 64})
    session.execute(sa.text(
        "INSERT INTO entitlement_events (id,entitlement_instance_id,transition,from_state,to_state,"
        "effective_at,actor_type,actor_id,source_type,source_id,idempotency_registry_id,evidence_json) "
        "VALUES (:id,:i,'test',:f,:t,:at,'system','x','test','x',:r,'{}')"
    ), {"id": str(uuid.uuid4()), "i": instance_id, "f": from_state, "t": to_state, "at": effective_at,
        "r": registry_id})


@pytest.mark.postgres
@PG
def test_postgres_f3_only_initial_approval_is_gated_and_later_lifecycle_remains_open():
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed_account(session)

            def redeemed_instance():
                redemption, *_ = redeem(session, ns, offer_definition(session, days=30))
                session.commit()
                return redemption

            # Approved disposition: active -> reducing -> expired before the term ends.
            first = redeemed_instance()
            _transition(session, first.entitlement_instance_id, "active", "reducing", db_now(session))
            _transition(session, first.entitlement_instance_id, "reducing", "expired", db_now(session))
            session.commit()
            assert session.get(EntitlementInstance, first.entitlement_instance_id).state == "expired"
            # Replacement: active -> reducing -> superseded.
            second = redeemed_instance()
            _transition(session, second.entitlement_instance_id, "active", "reducing", db_now(session))
            _transition(session, second.entitlement_instance_id, "reducing", "superseded", db_now(session))
            session.commit()
            assert session.get(EntitlementInstance, second.entitlement_instance_id).state == "superseded"
            # Term-end expiry (active -> expired) still waits for the term to end,
            # judged by database time, whatever effective time is claimed.
            third = redeemed_instance()
            ends_at = _utc(third.term_ends_at)
            for claimed in (db_now(session), ends_at):
                with pytest.raises(sa.exc.DBAPIError, match="before its term ends"):
                    _transition(session, third.entitlement_instance_id, "active", "expired", claimed)
                session.rollback()
            # Cancelling a proposed offer instance needs no redemption.
            definition = session.get(EntitlementDefinition, offer_definition(session))
            session.commit()
            instance_id = str(uuid.uuid4())
            session.execute(sa.text(
                "INSERT INTO entitlement_instances (id,billing_account_id,entitlement_definition_id,state,"
                "starts_at,ends_at,source_type,source_id,approval_evidence_reference) VALUES "
                "(:id,:a,:d,'proposed',now(),now() + interval '1 day','trial',:id,'approval:test')"
            ), {"id": instance_id, "a": ns.account, "d": definition.id})
            _transition(session, instance_id, "proposed", "cancelled", db_now(session))
            session.commit()
            assert session.get(EntitlementInstance, instance_id).state == "cancelled"
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# Audit R2: authorization uses actual current time, not the transaction start
# ---------------------------------------------------------------------------

def _clock(engine):
    with engine.connect() as connection:
        return _utc(connection.execute(sa.text("SELECT clock_timestamp()")).scalar_one())


# Each R2 test's deadline is ``_clock() + R2_WINDOW_SECONDS + extra`` read
# right after the account is seeded. The window only has to outlast the test's
# own setup (creating the grant or offer, committing, opening the redeeming
# transaction) so the "before the deadline" step really happens before it; a
# 1-second window failed on a slow shared CI runner (Nov 24, 2026). Every
# assertion about which side of the deadline each step is on is unchanged.
R2_WINDOW_SECONDS = 5


def _wait_past(engine, deadline):
    """Wait until the database clock has passed ``deadline`` (bounded)."""
    import time
    give_up = time.monotonic() + R2_WINDOW_SECONDS + 15
    while time.monotonic() < give_up:
        if _clock(engine) > deadline:
            return
        time.sleep(0.05)
    raise AssertionError("database clock did not pass the deadline")


def _r2_setup(engine, *, grant_seconds=None, retire_seconds=None):
    with Session(engine, expire_on_commit=False) as session:
        ns = seed_account(session)
        deadline = _clock(engine) + timedelta(seconds=R2_WINDOW_SECONDS + (grant_seconds or retire_seconds))
        if grant_seconds is not None:
            member = staff(session, COMP_PERMISSION, starts_at=ANCHOR, ends_at=deadline)
            definition_id = offer_definition(session, origin="comp", capabilities={}, per_account=10)
            actor = staff_actor(member)
        else:
            member = None
            definition_id = offer_definition(session, capabilities={}, per_account=10, retired_at=deadline)
            actor = SYSTEM
        session.commit()
        before = _redemption_effects(session, ns.account)
    return ns, definition_id, actor, deadline, before


@pytest.mark.postgres
@PG
@pytest.mark.parametrize("deadline_kind", ["grant_expiry", "offer_retirement"])
def test_postgres_r2_transaction_opened_before_the_deadline_cannot_redeem_after_it(deadline_kind):
    """The audit reproduction: a READ COMMITTED transaction starts before the
    grant expires (or the offer retires), waits past the deadline, then redeems."""
    engine = _migrated_engine()
    try:
        kwargs = {"grant_seconds": 1} if deadline_kind == "grant_expiry" else {"retire_seconds": 1}
        ns, definition_id, actor, deadline, before = _r2_setup(engine, **kwargs)
        redeeming = _begin_snapshot(engine, "READ COMMITTED")
        try:
            started = _utc(redeeming.execute(sa.text("SELECT now()")).scalar_one())
            assert started < deadline
            _wait_past(engine, deadline)
            expected = OfferPermissionError if deadline_kind == "grant_expiry" else OfferDependencyError
            with pytest.raises(expected):
                redeem(redeeming, ns, definition_id, actor=actor)
            redeeming.rollback()
        finally:
            redeeming.close()
        with Session(engine) as session:
            assert _redemption_effects(session, ns.account) == before
            assert session.query(CreditOfferFunding).filter_by(billing_account_id=ns.account).count() == 0
    finally:
        engine.dispose()


@pytest.mark.postgres
@PG
@pytest.mark.parametrize("deadline_kind", ["grant_expiry", "offer_retirement"])
def test_postgres_r2_database_guard_refuses_even_if_the_service_used_transaction_start(
    deadline_kind, monkeypatch,
):
    """Independent database enforcement: make the service judge authority at
    the transaction start (the pre-R2 behaviour); the guard must still refuse."""
    import app.billing_offers as offers

    engine = _migrated_engine()
    try:
        kwargs = {"grant_seconds": 1} if deadline_kind == "grant_expiry" else {"retire_seconds": 1}
        ns, definition_id, actor, deadline, before = _r2_setup(engine, **kwargs)
        monkeypatch.setattr(offers, "_database_clock", offers._database_now)
        redeeming = _begin_snapshot(engine, "READ COMMITTED")
        try:
            _wait_past(engine, deadline)
            message = ("explicit, active, unrevoked staff permission" if deadline_kind == "grant_expiry"
                       else "approved, effective offer definition")
            with pytest.raises(sa.exc.DBAPIError, match=message):
                redeem(redeeming, ns, definition_id, actor=actor)
            redeeming.rollback()
        finally:
            redeeming.close()
        with Session(engine) as session:
            assert _redemption_effects(session, ns.account) == before
    finally:
        engine.dispose()


@pytest.mark.postgres
@PG
@pytest.mark.parametrize("deadline_kind", ["grant_expiry", "offer_retirement"])
def test_postgres_r2_deadline_between_insert_and_commit_refuses_the_commit(deadline_kind):
    """No check-then-wait gap: authority checked at insert is re-checked at commit."""
    engine = _migrated_engine()
    try:
        kwargs = {"grant_seconds": 2} if deadline_kind == "grant_expiry" else {"retire_seconds": 2}
        ns, definition_id, actor, deadline, before = _r2_setup(engine, **kwargs)
        with Session(engine, expire_on_commit=False) as redeeming:
            _r, _f, _l, state = redeem(redeeming, ns, definition_id, actor=actor)
            assert state == "inserted" and _clock(engine) < deadline
            _wait_past(engine, deadline)
            with pytest.raises(sa.exc.DBAPIError, match="before the redemption committed"):
                redeeming.commit()
            redeeming.rollback()
        with Session(engine) as session:
            assert _redemption_effects(session, ns.account) == before
    finally:
        engine.dispose()


@pytest.mark.postgres
@PG
@pytest.mark.parametrize("deadline_kind", ["grant_expiry", "offer_retirement"])
def test_postgres_r2_redemption_before_the_deadline_is_valid_and_retries_after_it(deadline_kind):
    engine = _migrated_engine()
    try:
        kwargs = {"grant_seconds": 3} if deadline_kind == "grant_expiry" else {"retire_seconds": 3}
        ns, definition_id, actor, deadline, _before = _r2_setup(engine, **kwargs)
        with Session(engine, expire_on_commit=False) as session:
            redemption, _f, _l, state = redeem(session, ns, definition_id, redemption_id="just-in-time", actor=actor)
            session.commit()
        assert state == "inserted" and _utc(redemption.redeemed_at) < deadline
        _wait_past(engine, deadline)
        with Session(engine, expire_on_commit=False) as session:
            effects = _redemption_effects(session, ns.account)
            again, _f, _l, state = redeem(session, ns, definition_id, redemption_id="just-in-time", actor=actor)
            session.commit()
            assert (state, again.id) == ("duplicate", redemption.id)
            assert _utc(again.redeemed_at) == _utc(redemption.redeemed_at)
            assert _redemption_effects(session, ns.account) == effects
            with pytest.raises((OfferPermissionError, OfferDependencyError)):
                redeem(session, ns, definition_id, redemption_id="too-late", actor=actor)
            session.rollback()
    finally:
        engine.dispose()
