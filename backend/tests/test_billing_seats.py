"""Phase 8 seat-commitment coverage (lifecycle D09; D17 T-SEAT-01..10).

Unit tests run against the ORM schema (SQLite by default, an isolated
PostgreSQL schema when TEST_DATABASE_URL is set). ``test_postgres_*`` tests
run against the fully migrated PostgreSQL database, where the Phase 8 guards
are installed.
"""

from concurrent.futures import ThreadPoolExecutor
import contextlib
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import re
import threading
from types import SimpleNamespace
import uuid

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy.orm import Session

from app import db as flask_db
from app.billing_allocations import _claim_registry
from app.billing_entitlements import add_calendar_months
from app.billing_inbox import claim_next_event, mark_processed
from app.billing_outbox import record_domain_event
from app.billing_seats import (
    PAID_OCCUPANCY_ROLES,
    SeatChangeConflictError,
    SeatChangeError,
    SeatChangeIsolationError,
    SeatChangePermissionError,
    SeatFundingDependencyError,
    SeatFundingError,
    apply_paid_seat_increase,
    apply_seat_reduction,
    record_seat_funding_attribution,
    record_seat_renewal_funding,
    resolve_seat_term_funding,
    seat_renewal_requirement,
    cancel_seat_change,
    current_seat_commitment,
    mark_seat_renewal_unpaid,
    open_seat_commitment,
    record_seat_change_approaching,
    reevaluate_blocked_reduction,
    request_seat_reduction,
    seat_occupancy,
)
from app.models import (
    BillingAccount,
    BillingRoleGrant,
    BillingSubscription,
    CommunicationOutbox,
    CreditLedgerEntry,
    CreditLot,
    DomainEvent,
    EntitlementDefinition,
    ExternalEventInbox,
    FinancialLine,
    FinancialTransaction,
    IdempotencyRegistry,
    Organization,
    OrganizationMember,
    SeatChange,
    SeatChangeEvent,
    SeatCommitment,
    SeatCommitmentFence,
    SeatFundingAttribution,
    SeatFundingUse,
    SeatTermFunding,
    User,
    UserSession,
)
from app.orgs import ORG_ROLES, _ROLE_ALIAS, normalize_org_role


BACKEND_DIR = Path(__file__).resolve().parents[1]
MIGRATIONS_DIR = str(BACKEND_DIR / "migrations")
REVISION = "b8c2d4e6f8a1"
PARENT = "a7d9e2f4b6c8"
PHASE8_TABLES = (
    "seat_change_events", "seat_funding_uses", "seat_term_fundings", "seat_funding_attributions",
    "seat_changes", "seat_commitments", "seat_commitment_fences",
)
ANCHOR = datetime(2026, 1, 31, 15, 45, tzinfo=timezone.utc)
INCLUDED = 3  # test plan definition only; not a commercial allowance


def _capabilities(included):
    capabilities = {"analysis": True}
    if included is not None:
        capabilities["included_seats"] = included
    return {"schema_version": 1, "capabilities": capabilities}
DELIVERIES = ({
    "template_key": "test-seat-change", "template_version": "test-v1",
    "channel": "test-channel", "locale": "en-US",
},)
PG = pytest.mark.skipif(
    not os.environ.get("TEST_DATABASE_URL"),
    reason="local disposable PostgreSQL is not configured",
)


def _utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


# ---------------------------------------------------------------------------
# Seeding (works with the Flask session and with a plain migrated Session)
# ---------------------------------------------------------------------------

def _user(session, suffix, name):
    user = User(
        id=f"p8-{name}-{suffix}", email=f"p8-{name}-{suffix}@example.test",
        name=f"Phase 8 {name}", password_hash="not-a-login-credential",
        subscription_plan="free", credits_remaining=0, seat_limit=1, max_seats=1,
    )
    session.add(user)
    session.flush()
    return user


def add_member(session, organization_id, user_id, role, status="active"):
    member = OrganizationMember(
        organization_id=organization_id, user_id=user_id, role=role, status=status,
    )
    session.add(member)
    session.flush()
    return member


def paid_line(session, account_id, subscription_id, kind, paid_at, suffix, *, tx_kind="payment", principal=2500,
              currency="usd", quantity=1):
    now = datetime.now(timezone.utc)
    inbox = ExternalEventInbox(
        id=f"p8-inbox-{suffix}", provider="stripe", event_id=f"p8_evt_{suffix}",
        event_type="invoice.payment_succeeded", object_type="invoice",
        object_id=f"p8_in_{suffix}", payload_digest="d" * 64,
        summary_json={"schema_version": 1}, livemode=False,
        provider_created_at=paid_at, received_at=now, state="received",
    )
    session.add(inbox)
    session.flush()
    claimed = claim_next_event(session, now=now, lease_seconds=60)
    assert claimed.id == inbox.id
    mark_processed(session, inbox.id, claimed.attempt_count, now=now + timedelta(seconds=1))
    transaction = FinancialTransaction(
        id=f"p8-tx-{suffix}", billing_account_id=account_id, kind=tx_kind,
        provider="stripe", object_type="invoice", object_id=f"p8_in_{suffix}",
        external_version="v1", effective_at=paid_at, currency=currency,
        principal_minor=principal, tax_minor=0, fee_minor=0, discount_minor=0,
        gross_minor=principal, inbox_event_id=inbox.id,
    )
    session.add(transaction)
    session.flush()
    line = FinancialLine(
        id=f"p8-line-{suffix}", financial_transaction_id=transaction.id,
        external_line_id=f"p8_il_{suffix}", line_kind=kind, source_type="stripe_price",
        source_id=f"price_{suffix}", quantity=quantity, currency=currency,
        principal_minor=principal, tax_minor=0, fee_minor=0, discount_minor=0,
        subscription_id=subscription_id,
    )
    session.add(line)
    session.flush()
    return line.id


def _line_suffix(line_id):
    return line_id[len("p8-line-"):]


def attribute(session, subscription_id, line_id, source, term_starts_at, term_ends_at, seats=None):
    subscription = session.get(BillingSubscription, subscription_id)
    attribution, _state = record_seat_funding_attribution(
        session, billing_account_id=subscription.billing_account_id, subscription_id=subscription_id,
        financial_line_id=line_id, seat_source=source, seats=seats,
        term_starts_at=term_starts_at, term_ends_at=term_ends_at,
        evidence_reference=f"adapter:{line_id}", actor_type="system", actor_id="phase8-test",
    )
    return attribution.id


def seed(session, *, suffix=None, interval="month", quantity=5, extra_roles=("admin", "creator"),
         included=INCLUDED, open_commitment=True):
    """Organization with an owner (no billing grant), billing users, and a paid subscription.

    The opening is funded by the base plan's included seats (from the approved
    test definition) plus separately purchased seats for the remainder.
    """
    suffix = suffix or uuid.uuid4().hex[:10]
    owner = _user(session, suffix, "owner")
    organization = Organization(
        id=f"p8-org-{suffix}", name=f"Phase 8 {suffix}", slug=f"phase-8-{suffix}",
        owner_user_id=owner.id, plan_key="team",
    )
    session.add(organization)
    session.flush()
    add_member(session, organization.id, owner.id, "owner")
    for index, role in enumerate(extra_roles):
        member = _user(session, suffix, f"member{index}")
        add_member(session, organization.id, member.id, role)
    account = BillingAccount(
        id=f"p8-account-{suffix}", organization_id=organization.id,
        status="active", currency="usd", account_anchor_at=ANCHOR,
    )
    definition = EntitlementDefinition(
        id=f"p8-definition-{suffix}", key=f"team-{suffix}", version=1,
        exclusivity_key="base-plan", capability_json=_capabilities(included),
        funding_policy_json={
            "schema_version": 1,
            "period_kind": "annual_monthly" if interval == "year" else "monthly_subscription",
            "credit_amount": 500,
        },
        effective_at=ANCHOR, approved_at=ANCHOR, approval_evidence_reference="approval:p8",
    )
    session.add_all([account, definition])
    session.flush()
    users = {}
    for name, role in (("payer", "billing_owner"), ("badmin", "billing_admin"), ("bviewer", "billing_viewer")):
        user = _user(session, suffix, name)
        users[name] = user.id
        session.add(BillingRoleGrant(
            id=f"p8-grant-{name}-{suffix}", billing_account_id=account.id, user_id=user.id,
            role=role, state="active", starts_at=ANCHOR - timedelta(days=30),
            origin_type="test", origin_id=f"seed:{suffix}",
        ))
    session.flush()
    term_end = add_calendar_months(ANCHOR, 12 if interval == "year" else 1)
    subscription = BillingSubscription(
        id=f"p8-subscription-{suffix}", billing_account_id=account.id, processor="stripe",
        external_subscription_id=f"p8_sub_{suffix}", interval=interval, anchor_at=ANCHOR,
        term_starts_at=ANCHOR, term_ends_at=term_end,
        state="active", current_entitlement_definition_id=definition.id,
        origin_evidence_json={"test": "phase8"},
    )
    session.add(subscription)
    session.flush()
    base_line = paid_line(session, account.id, subscription.id, "subscription", ANCHOR, f"open-{suffix}")
    seat_line = paid_line(session, account.id, subscription.id, "seat", ANCHOR, f"openseat-{suffix}")
    ns = SimpleNamespace(
        suffix=suffix, org=organization.id, owner=owner.id, account=account.id,
        subscription=subscription.id, opening=None, base_line=base_line, seat_line=seat_line,
        opening_attributions=[], renewal=_utc(term_end), definition=definition.id, **users,
    )
    if open_commitment:
        ns.opening_attributions = [attribute(session, subscription.id, base_line, "included", ANCHOR, term_end)]
        if quantity > (included or 0):
            ns.opening_attributions.append(attribute(
                session, subscription.id, seat_line, "purchased", ANCHOR, term_end, seats=quantity - included,
            ))
        commitment, state = open_seat_commitment(
            session, billing_account_id=account.id, subscription_id=subscription.id,
            quantity=quantity, attribution_ids=ns.opening_attributions, opened_at=ANCHOR,
            actor_type="system", actor_id="phase8-test", delivery_obligations=DELIVERIES,
        )
        assert state == "inserted"
        ns.opening = commitment.id
    session.commit()
    return ns


def increase(session, ns, command, delta, line_id, paid_at, user=None, requested_at=None, seats=None,
             attribution_ids=None):
    """Paid increase; by default the line funds exactly ``delta`` purchased seats."""
    if attribution_ids is None:
        term_end = _utc(session.get(BillingSubscription, ns.subscription).term_ends_at)
        attribution_ids = [attribute(
            session, ns.subscription, line_id, "purchased", paid_at, term_end,
            seats=delta if seats is None else seats,
        )]
    return apply_paid_seat_increase(
        session, billing_account_id=ns.account, subscription_id=ns.subscription,
        client_command_id=command, seat_delta=delta, attribution_ids=attribution_ids,
        requested_at=requested_at or paid_at, paid_at=paid_at,
        requested_by_user_id=user or ns.payer, delivery_obligations=DELIVERIES,
    )


def renewal_funding(session, subscription_id, term_starts_at, line_id, seats):
    """Fund ``seats`` for the term starting at ``term_starts_at`` from one paid line.

    A subscription line carries the plan's included seats; any seats above that
    come from a deterministic companion seat line. A seat line given directly
    is paired with a deterministic base-plan line.
    """
    subscription = session.get(BillingSubscription, subscription_id)
    months = 12 if subscription.interval == "year" else 1
    term_end = add_calendar_months(term_starts_at, months)
    line = session.get(FinancialLine, line_id)
    paid_at = _utc(session.get(FinancialTransaction, line.financial_transaction_id).effective_at)
    suffix = _line_suffix(line_id)
    if line.line_kind == "subscription":
        base_line, seat_line = line_id, f"p8-line-{suffix}-x"
        if seats > INCLUDED and session.get(FinancialLine, seat_line) is None:
            paid_line(session, subscription.billing_account_id, subscription_id, "seat", paid_at, f"{suffix}-x")
    else:
        base_line, seat_line = f"p8-line-{suffix}-b", line_id
        if session.get(FinancialLine, base_line) is None:
            paid_line(session, subscription.billing_account_id, subscription_id, "subscription", paid_at, f"{suffix}-b")
    ids = [attribute(session, subscription_id, base_line, "included", term_starts_at, term_end)]
    if seats > INCLUDED:
        ids.append(attribute(session, subscription_id, seat_line, "purchased", term_starts_at, term_end,
                             seats=seats - INCLUDED))
    return ids


def renew(session, change_id, line_id, applied_at, seats=None, actor_id="renewal"):
    """Apply a reduction at its renewal; by default the renewal funds the target."""
    change = session.get(SeatChange, change_id)
    ids = renewal_funding(
        session, change.subscription_id, _utc(change.effective_at), line_id,
        change.target_quantity if seats is None else seats,
    )
    return apply_seat_reduction(
        session, seat_change_id=change_id, attribution_ids=ids, applied_at=applied_at,
        actor_id=actor_id, delivery_obligations=DELIVERIES,
    )


def reduce(session, ns, command, target, requested_at, user=None, supersede=False, effective_at=None):
    return request_seat_reduction(
        session, billing_account_id=ns.account, subscription_id=ns.subscription,
        client_command_id=command, target_quantity=target, requested_at=requested_at,
        effective_at=effective_at or ns.renewal, requested_by_user_id=user or ns.badmin,
        compatible_supersede=supersede, delivery_obligations=DELIVERIES,
    )


def _members(session, org):
    return sorted(
        (m.id, m.user_id, m.role, m.status)
        for m in session.query(OrganizationMember).filter_by(organization_id=org).all()
    )


def _counts(session, account):
    return (
        session.query(DomainEvent).filter_by(billing_account_id=account).count(),
        session.query(CommunicationOutbox).filter_by(billing_account_id=account).count(),
        session.query(SeatChange).filter_by(billing_account_id=account).count(),
        session.query(SeatCommitment).filter_by(billing_account_id=account).count(),
    )


# ---------------------------------------------------------------------------
# Commitment versus occupancy (T-SEAT-01)
# ---------------------------------------------------------------------------

def test_commitment_and_occupancy_are_separate_projections(db):
    ns = seed(db.session, extra_roles=("admin", "creator", "viewer", "member", "editor", "teammate"))
    inactive = _user(db.session, ns.suffix, "former")
    add_member(db.session, ns.org, inactive.id, "collaborator", status="removed")
    db.session.commit()
    # owner + admin + creator + member(alias) + editor(alias) + teammate(alias); viewer and removed excluded.
    assert seat_occupancy(db.session, ns.org) == 6
    commitment = current_seat_commitment(db.session, ns.subscription)
    assert commitment.quantity == 5 and commitment.origin_type == "opening"
    add_member(db.session, ns.org, _user(db.session, ns.suffix, "late").id, "creator")
    db.session.commit()
    assert seat_occupancy(db.session, ns.org) == 7
    assert current_seat_commitment(db.session, ns.subscription).quantity == 5


def test_opening_requires_paid_subscription_evidence_and_is_once_only(db):
    ns = seed(db.session)
    replay = open_seat_commitment(
        db.session, billing_account_id=ns.account, subscription_id=ns.subscription,
        quantity=5, attribution_ids=ns.opening_attributions, opened_at=ANCHOR,
        actor_type="system", actor_id="phase8-test", delivery_obligations=DELIVERIES,
    )
    assert replay[1] == "duplicate" and replay[0].id == ns.opening
    with pytest.raises(SeatChangeConflictError):
        open_seat_commitment(
            db.session, billing_account_id=ns.account, subscription_id=ns.subscription,
            quantity=9, attribution_ids=ns.opening_attributions, opened_at=ANCHOR,
            actor_type="system", actor_id="phase8-test", delivery_obligations=DELIVERIES,
        )
    db.session.rollback()


# ---------------------------------------------------------------------------
# Permissions and organization isolation
# ---------------------------------------------------------------------------

def test_seat_changes_require_explicit_billing_permission(db):
    ns = seed(db.session)
    paid_at = ANCHOR + timedelta(days=10)
    line = paid_line(db.session, ns.account, ns.subscription, "seat", paid_at, f"perm-{ns.suffix}")
    db.session.commit()
    before = _counts(db.session, ns.account)
    # Organization owner and plain organization admin hold no billing grant.
    admin_member = db.session.query(OrganizationMember).filter_by(organization_id=ns.org, role="admin").one()
    for user in (ns.owner, admin_member.user_id, ns.bviewer, f"p8-unknown-{ns.suffix}"):
        with pytest.raises(SeatChangePermissionError):
            increase(db.session, ns, f"perm-{user}", 1, line, paid_at, user=user)
        db.session.rollback()
        with pytest.raises(SeatChangePermissionError):
            reduce(db.session, ns, f"perm-red-{user}", 3, paid_at, user=user)
        db.session.rollback()
    assert _counts(db.session, ns.account) == before
    # A billing admin manages schedules but cannot authorize new spending.
    with pytest.raises(SeatChangePermissionError, match="billing owner"):
        increase(db.session, ns, "admin-spend", 1, line, paid_at, user=ns.badmin)
    db.session.rollback()
    # A revoked billing owner grant is not authority.
    other = seed(db.session)
    other_line = paid_line(db.session, other.account, other.subscription, "seat", paid_at, f"rv-{other.suffix}")
    grant = db.session.get(BillingRoleGrant, f"p8-grant-payer-{other.suffix}")
    grant.state = "revoked"
    grant.ends_at = ANCHOR
    db.session.commit()
    with pytest.raises(SeatChangePermissionError):
        increase(db.session, other, "revoked", 1, other_line, paid_at)
    db.session.rollback()
    # Billing owner (not an organization member) is authorized.
    change, commitment, state = increase(db.session, ns, "owner-ok", 1, line, paid_at, user=ns.payer)
    db.session.commit()
    assert state == "inserted" and commitment.quantity == 6
    assert db.session.get(BillingRoleGrant, change.authorizing_role_grant_id).role == "billing_owner"


def test_cross_organization_commands_are_refused(db):
    a = seed(db.session)
    b = seed(db.session)
    paid_at = ANCHOR + timedelta(days=5)
    b_line = paid_line(db.session, b.account, b.subscription, "seat", paid_at, f"x-{b.suffix}")
    a_line = paid_line(db.session, a.account, a.subscription, "seat", paid_at, f"x-{a.suffix}")
    db.session.commit()
    before = (_counts(db.session, a.account), _counts(db.session, b.account))
    # Organization A's billing admin cannot act on organization B.
    with pytest.raises(SeatChangePermissionError):
        increase(db.session, b, "cross-user", 1, b_line, paid_at, user=a.badmin)
    db.session.rollback()
    # A subscription cannot be addressed through another organization's account.
    with pytest.raises(SeatChangeError):
        apply_paid_seat_increase(
            db.session, billing_account_id=a.account, subscription_id=b.subscription,
            client_command_id="cross-sub", seat_delta=1, attribution_ids=["not-an-attribution"],
            requested_at=paid_at, paid_at=paid_at, requested_by_user_id=a.badmin,
            delivery_obligations=DELIVERIES,
        )
    db.session.rollback()
    # Another organization's payment cannot fund this organization's seats.
    with pytest.raises(SeatChangeError):
        increase(db.session, a, "cross-line", 1, b_line, paid_at)
    db.session.rollback()
    change, _state = reduce(db.session, b, "b-red", 3, paid_at, user=b.badmin)
    db.session.commit()
    with pytest.raises(SeatChangePermissionError):
        cancel_seat_change(
            db.session, seat_change_id=change.id, cancelled_at=paid_at + timedelta(hours=1),
            requested_by_user_id=a.badmin, delivery_obligations=DELIVERIES,
        )
    db.session.rollback()
    assert db.session.get(SeatChange, change.id).state == "scheduled_reduction"
    assert _counts(db.session, a.account) == before[0]
    assert a_line  # A's own evidence is untouched and still usable.


# ---------------------------------------------------------------------------
# Paid increases (T-SEAT-02)
# ---------------------------------------------------------------------------

def test_paid_increase_requires_matching_seat_payment(db):
    ns = seed(db.session)
    paid_at = ANCHOR + timedelta(days=3)
    subscription_line = paid_line(db.session, ns.account, ns.subscription, "subscription", paid_at, f"s-{ns.suffix}")
    refund_line = paid_line(db.session, ns.account, ns.subscription, "seat", paid_at, f"r-{ns.suffix}", tx_kind="refund")
    seat_line = paid_line(db.session, ns.account, ns.subscription, "seat", paid_at, f"ok-{ns.suffix}")
    db.session.commit()
    before = _counts(db.session, ns.account)
    for command, line, at in (
        ("wrong-kind", subscription_line, paid_at),
        ("refund", refund_line, paid_at),
        ("wrong-time", seat_line, paid_at + timedelta(seconds=1)),
        ("after-term", seat_line, ns.renewal + timedelta(days=1)),
    ):
        with pytest.raises(SeatChangeError):
            increase(db.session, ns, command, 1, line, at)
        db.session.rollback()
    with pytest.raises(SeatChangeError):
        increase(db.session, ns, "zero", 0, seat_line, paid_at)
    db.session.rollback()
    with pytest.raises(SeatChangeError):
        increase(db.session, ns, "late-request", 1, seat_line, paid_at, requested_at=paid_at + timedelta(minutes=1))
    db.session.rollback()
    assert _counts(db.session, ns.account) == before
    assert current_seat_commitment(db.session, ns.subscription).quantity == 5


def test_paid_increase_applies_delta_once_and_replays_exactly(db):
    ns = seed(db.session)
    paid_at = ANCHOR + timedelta(days=10)
    line = paid_line(db.session, ns.account, ns.subscription, "seat", paid_at, f"inc-{ns.suffix}")
    db.session.commit()
    change, commitment, state = increase(db.session, ns, "add-two", 2, line, paid_at)
    db.session.commit()
    assert state == "inserted" and change.state == "increased"
    assert (change.base_quantity, change.target_quantity, commitment.quantity) == (5, 7, 7)
    opening = db.session.get(SeatCommitment, ns.opening)
    assert opening.state == "replaced" and _utc(opening.ends_at) == paid_at
    assert commitment.previous_commitment_id == opening.id
    assert change.command_key == f"seat:{ns.org}:add-two"
    event = db.session.get(DomainEvent, change.domain_event_id)
    assert event.event_type == "seat_change_applied"
    assert db.session.query(CommunicationOutbox).filter_by(domain_event_id=event.id).count() == 1
    before = _counts(db.session, ns.account)
    replay = increase(db.session, ns, "add-two", 2, line, paid_at)
    db.session.commit()
    assert replay[2] == "duplicate" and replay[0].id == change.id and replay[1].id == commitment.id
    assert _counts(db.session, ns.account) == before
    with pytest.raises(SeatChangeConflictError):
        increase(db.session, ns, "add-two", 3, line, paid_at)
    db.session.rollback()
    # One paid seat line funds one increase.
    with pytest.raises(Exception):
        increase(db.session, ns, "reuse-line", 2, line, paid_at)
        db.session.flush()
    db.session.rollback()
    assert current_seat_commitment(db.session, ns.subscription).quantity == 7


# ---------------------------------------------------------------------------
# Reductions, occupancy, payment outcomes (T-SEAT-03..09)
# ---------------------------------------------------------------------------

def test_reduction_schedules_at_monthly_renewal_and_applies_after_payment(db):
    ns = seed(db.session)  # occupancy 3 (owner, admin, creator), commitment 5
    members = _members(db.session, ns.org)
    requested = ANCHOR + timedelta(days=2)
    # Month-end clamp: Jan 31 monthly term renews Feb 28 at the anchor time.
    assert ns.renewal == datetime(2026, 2, 28, 15, 45, tzinfo=timezone.utc)
    with pytest.raises(SeatChangeError):
        reduce(db.session, ns, "wrong-effective", 4, requested, effective_at=datetime(2026, 3, 3, 15, 45, tzinfo=timezone.utc))
    db.session.rollback()
    for bad_target in (5, 6):
        with pytest.raises(SeatChangeError):
            reduce(db.session, ns, f"not-lower-{bad_target}", bad_target, requested)
        db.session.rollback()
    change, state = reduce(db.session, ns, "to-four", 4, requested)
    db.session.commit()
    assert state == "inserted" and change.state == "scheduled_reduction"
    assert _utc(change.effective_at) == ns.renewal and change.occupancy_at_request == 3
    assert db.session.get(DomainEvent, change.domain_event_id).event_type == "seat_change_scheduled"
    assert current_seat_commitment(db.session, ns.subscription).quantity == 5
    renewal_line = paid_line(db.session, ns.account, ns.subscription, "subscription", ns.renewal, f"ren-{ns.suffix}")
    db.session.commit()
    with pytest.raises(SeatChangeError):
        renew(db.session, change.id, renewal_line, ns.renewal - timedelta(seconds=1))
    db.session.rollback()
    applied, commitment, state = renew(db.session, change.id, renewal_line, ns.renewal)
    db.session.commit()
    assert state == "inserted" and applied.state == "reduced"
    assert commitment.quantity == 4 and commitment.origin_type == "reduction"
    assert applied.result_commitment_id == commitment.id
    assert db.session.get(SeatCommitment, ns.opening).state == "replaced"
    before = _counts(db.session, ns.account)
    replay = renew(db.session, change.id, renewal_line, ns.renewal)
    db.session.commit()
    assert replay[2] == "duplicate" and _counts(db.session, ns.account) == before
    assert _members(db.session, ns.org) == members


def test_annual_reduction_waits_for_annual_renewal(db):
    ns = seed(db.session, interval="year")
    assert ns.renewal == datetime(2027, 1, 31, 15, 45, tzinfo=timezone.utc)
    with pytest.raises(SeatChangeError):
        reduce(db.session, ns, "monthly-guess", 4, ANCHOR + timedelta(days=1),
               effective_at=datetime(2026, 2, 28, 15, 45, tzinfo=timezone.utc))
    db.session.rollback()
    change, _state = reduce(db.session, ns, "annual", 4, ANCHOR + timedelta(days=1))
    db.session.commit()
    assert _utc(change.effective_at) == ns.renewal
    mid_year = paid_line(db.session, ns.account, ns.subscription, "subscription", datetime(2026, 6, 30, tzinfo=timezone.utc), f"mid-{ns.suffix}")
    db.session.commit()
    with pytest.raises(SeatChangeError):
        renew(db.session, change.id, mid_year, datetime(2026, 6, 30, tzinfo=timezone.utc))
    db.session.rollback()
    assert current_seat_commitment(db.session, ns.subscription).quantity == 5


def test_reduction_blocked_by_occupancy_then_resolved_by_admin(db):
    ns = seed(db.session, extra_roles=("admin", "creator", "collaborator"))  # occupancy 4
    members_before = _members(db.session, ns.org)
    requested = ANCHOR + timedelta(days=1)
    change, state = reduce(db.session, ns, "to-three", 3, requested)
    db.session.commit()
    assert state == "inserted" and change.state == "blocked_occupancy"
    assert change.occupancy_at_request == 4
    event = db.session.get(DomainEvent, change.domain_event_id)
    assert event.event_type == "seat_reduction_blocked"
    assert db.session.query(CommunicationOutbox).filter_by(domain_event_id=event.id).count() == 1
    assert current_seat_commitment(db.session, ns.subscription).quantity == 5
    assert _members(db.session, ns.org) == members_before  # nobody removed or downgraded
    before = _counts(db.session, ns.account)
    still = reevaluate_blocked_reduction(
        db.session, seat_change_id=change.id, evaluated_at=requested + timedelta(days=1),
        requested_by_user_id=ns.badmin, delivery_obligations=DELIVERIES,
    )
    db.session.commit()
    assert still[1] == "still_blocked" and _counts(db.session, ns.account) == before
    with pytest.raises(SeatChangePermissionError):
        reevaluate_blocked_reduction(
            db.session, seat_change_id=change.id, evaluated_at=requested + timedelta(days=1),
            requested_by_user_id=ns.owner, delivery_obligations=DELIVERIES,
        )
    db.session.rollback()
    # The membership authority (not billing) deactivates a member.
    collaborator = db.session.query(OrganizationMember).filter_by(organization_id=ns.org, role="collaborator").one()
    collaborator.status = "removed"
    db.session.commit()
    resolved, state = reevaluate_blocked_reduction(
        db.session, seat_change_id=change.id, evaluated_at=requested + timedelta(days=2),
        requested_by_user_id=ns.badmin, delivery_obligations=DELIVERIES,
    )
    db.session.commit()
    assert state == "inserted" and resolved.state == "scheduled_reduction"
    assert _utc(resolved.effective_at) == ns.renewal
    replay = reevaluate_blocked_reduction(
        db.session, seat_change_id=change.id, evaluated_at=requested + timedelta(days=2),
        requested_by_user_id=ns.badmin, delivery_obligations=DELIVERIES,
    )
    assert replay[1] == "duplicate"
    db.session.rollback()


def test_occupancy_growth_before_renewal_preserves_commitment(db):
    ns = seed(db.session)  # occupancy 3
    change, _state = reduce(db.session, ns, "to-three", 3, ANCHOR + timedelta(days=1))
    db.session.commit()
    assert change.state == "scheduled_reduction"
    add_member(db.session, ns.org, _user(db.session, ns.suffix, "joiner").id, "collaborator")
    renewal_line = paid_line(db.session, ns.account, ns.subscription, "subscription", ns.renewal, f"g-{ns.suffix}")
    db.session.commit()
    blocked, commitment, state = renew(db.session, change.id, renewal_line, ns.renewal)
    db.session.commit()
    assert state == "blocked" and commitment is None and blocked.state == "blocked_occupancy"
    assert current_seat_commitment(db.session, ns.subscription).quantity == 5
    event = db.session.get(SeatChangeEvent, blocked.last_event_id)
    assert event.occupancy_observed == 4 and event.actor_type == "system"
    replay = renew(db.session, change.id, renewal_line, ns.renewal)
    assert replay[2] == "duplicate_blocked"
    db.session.rollback()
    # After resolution the reduction targets the next renewal, which the
    # subscription authority (outside Phase 8) has advanced.
    subscription = db.session.get(BillingSubscription, ns.subscription)
    subscription.term_starts_at = ns.renewal
    subscription.term_ends_at = add_calendar_months(ANCHOR, 2)
    joiner = db.session.query(OrganizationMember).filter_by(user_id=f"p8-joiner-{ns.suffix}").one()
    joiner.status = "removed"
    db.session.commit()
    resolved, state = reevaluate_blocked_reduction(
        db.session, seat_change_id=change.id, evaluated_at=ns.renewal + timedelta(days=1),
        requested_by_user_id=ns.payer, delivery_obligations=DELIVERIES,
    )
    db.session.commit()
    assert state == "inserted"
    assert _utc(resolved.effective_at) == datetime(2026, 3, 31, 15, 45, tzinfo=timezone.utc)


def test_failed_renewal_preserves_commitment_and_later_success_applies(db):
    ns = seed(db.session)
    change, _state = reduce(db.session, ns, "to-four", 4, ANCHOR + timedelta(days=1))
    db.session.commit()
    with pytest.raises(SeatChangeError):
        mark_seat_renewal_unpaid(
            db.session, seat_change_id=change.id, observed_at=ns.renewal - timedelta(seconds=1),
            actor_id="renewal", delivery_obligations=DELIVERIES,
        )
    db.session.rollback()
    unpaid, state = mark_seat_renewal_unpaid(
        db.session, seat_change_id=change.id, observed_at=ns.renewal,
        actor_id="renewal", delivery_obligations=DELIVERIES,
    )
    db.session.commit()
    assert state == "inserted" and unpaid.state == "awaiting_payment"
    assert current_seat_commitment(db.session, ns.subscription).quantity == 5
    assert mark_seat_renewal_unpaid(
        db.session, seat_change_id=change.id, observed_at=ns.renewal,
        actor_id="renewal", delivery_obligations=DELIVERIES,
    )[1] == "duplicate"
    db.session.commit()
    late = ns.renewal + timedelta(days=3)
    late_line = paid_line(db.session, ns.account, ns.subscription, "subscription", late, f"late-{ns.suffix}")
    db.session.commit()
    applied, commitment, state = renew(db.session, change.id, late_line, late)
    db.session.commit()
    assert state == "inserted" and applied.state == "reduced" and commitment.quantity == 4
    assert _utc(commitment.starts_at) == late
    history = [e.to_state for e in db.session.query(SeatChangeEvent).filter_by(seat_change_id=change.id).order_by(SeatChangeEvent.effective_at)]
    assert history == ["awaiting_payment", "reduced"]


def test_later_success_with_incompatible_occupancy_stays_blocked(db):
    ns = seed(db.session)
    change, _state = reduce(db.session, ns, "to-three", 3, ANCHOR + timedelta(days=1))
    db.session.commit()
    mark_seat_renewal_unpaid(
        db.session, seat_change_id=change.id, observed_at=ns.renewal,
        actor_id="renewal", delivery_obligations=DELIVERIES,
    )
    add_member(db.session, ns.org, _user(db.session, ns.suffix, "dunning-joiner").id, "creator")
    late = ns.renewal + timedelta(days=2)
    late_line = paid_line(db.session, ns.account, ns.subscription, "seat", late, f"dl-{ns.suffix}")
    db.session.commit()
    blocked, commitment, state = renew(db.session, change.id, late_line, late)
    db.session.commit()
    assert state == "blocked" and blocked.state == "blocked_occupancy" and commitment is None
    assert current_seat_commitment(db.session, ns.subscription).quantity == 5


def test_cancellation_and_supersession_retain_audit_history(db):
    ns = seed(db.session)
    at = ANCHOR + timedelta(days=1)
    first, _state = reduce(db.session, ns, "first", 4, at)
    db.session.commit()
    with pytest.raises(SeatChangeConflictError):
        reduce(db.session, ns, "second", 3, at)
    db.session.rollback()
    second, state = reduce(db.session, ns, "second", 3, at, supersede=True)
    db.session.commit()
    assert state == "inserted" and second.supersedes_change_id == first.id
    assert db.session.get(SeatChange, first.id).state == "superseded"
    with pytest.raises(SeatChangePermissionError):
        cancel_seat_change(
            db.session, seat_change_id=second.id, cancelled_at=at + timedelta(hours=1),
            requested_by_user_id=ns.bviewer, delivery_obligations=DELIVERIES,
        )
    db.session.rollback()
    cancelled, state = cancel_seat_change(
        db.session, seat_change_id=second.id, cancelled_at=at + timedelta(hours=1),
        requested_by_user_id=ns.badmin, delivery_obligations=DELIVERIES,
    )
    db.session.commit()
    assert state == "inserted" and cancelled.state == "cancelled"
    assert cancel_seat_change(
        db.session, seat_change_id=second.id, cancelled_at=at + timedelta(hours=1),
        requested_by_user_id=ns.badmin, delivery_obligations=DELIVERIES,
    )[1] == "duplicate"
    db.session.commit()
    with pytest.raises(SeatChangeError):
        renew(db.session, second.id,
              paid_line(db.session, ns.account, ns.subscription, "subscription", ns.renewal, f"c-{ns.suffix}"),
              ns.renewal)
    db.session.rollback()
    # A paid increase supersedes an active reduction (D08 precedence analogue).
    third, _state = reduce(db.session, ns, "third", 4, at + timedelta(hours=2))
    paid_at = at + timedelta(days=1)
    line = paid_line(db.session, ns.account, ns.subscription, "seat", paid_at, f"sup-{ns.suffix}")
    db.session.commit()
    increase_change, commitment, _state = increase(db.session, ns, "grow", 1, line, paid_at)
    db.session.commit()
    assert db.session.get(SeatChange, third.id).state == "superseded"
    assert increase_change.supersedes_change_id == third.id and commitment.quantity == 6
    states = sorted(c.state for c in db.session.query(SeatChange).filter_by(subscription_id=ns.subscription))
    assert states == ["cancelled", "increased", "superseded", "superseded"]
    assert current_seat_commitment(db.session, ns.subscription).quantity == 6


def test_approaching_notice_is_audited_idempotent_and_changes_nothing(db):
    ns = seed(db.session)
    change, _state = reduce(db.session, ns, "notice", 4, ANCHOR + timedelta(days=1))
    db.session.commit()
    event, state = record_seat_change_approaching(
        db.session, seat_change_id=change.id, observed_at=ANCHOR + timedelta(days=20),
        delivery_obligations=DELIVERIES,
    )
    db.session.commit()
    assert state == "inserted" and event.event_type == "seat_change_approaching"
    before = _counts(db.session, ns.account)
    again, state = record_seat_change_approaching(
        db.session, seat_change_id=change.id, observed_at=ANCHOR + timedelta(days=25),
        delivery_obligations=DELIVERIES,
    )
    db.session.commit()
    assert state == "duplicate" and again.id == event.id
    assert _counts(db.session, ns.account) == before
    assert db.session.get(SeatChange, change.id).state == "scheduled_reduction"
    assert db.session.query(CommunicationOutbox).filter_by(domain_event_id=event.id).count() == 1
    blocked_ns = seed(db.session, extra_roles=("admin", "creator", "collaborator", "creator"))
    blocked, _state = reduce(db.session, blocked_ns, "blocked", 3, ANCHOR + timedelta(days=1))
    db.session.commit()
    with pytest.raises(SeatChangeError):
        record_seat_change_approaching(
            db.session, seat_change_id=blocked.id, observed_at=ANCHOR + timedelta(days=2),
            delivery_obligations=DELIVERIES,
        )
    db.session.rollback()
    other, _state = reduce(db.session, ns, "late-notice", 3, ANCHOR + timedelta(days=2), supersede=True)
    db.session.commit()
    with pytest.raises(SeatChangeError):
        record_seat_change_approaching(
            db.session, seat_change_id=other.id, observed_at=ns.renewal,
            delivery_obligations=DELIVERIES,
        )
    db.session.rollback()


def test_every_transition_requires_delivery_obligations_and_rolls_back(db):
    ns = seed(db.session)
    before = _counts(db.session, ns.account)
    for empty in ((), [], None):
        with pytest.raises(SeatChangeError):
            request_seat_reduction(
                db.session, billing_account_id=ns.account, subscription_id=ns.subscription,
                client_command_id="no-delivery", target_quantity=4,
                requested_at=ANCHOR + timedelta(days=1), effective_at=ns.renewal,
                requested_by_user_id=ns.badmin, compatible_supersede=False,
                delivery_obligations=empty,
            )
        db.session.rollback()
    # Failure after the registry claim leaves no registry, event, or outbox row.
    registries = db.session.query(IdempotencyRegistry).count()
    with pytest.raises(SeatChangeError):
        reduce(db.session, ns, "terminal", 4, ANCHOR + timedelta(days=1), effective_at=ns.renewal + timedelta(days=1))
    db.session.rollback()
    assert db.session.query(IdempotencyRegistry).count() == registries
    assert _counts(db.session, ns.account) == before


# ---------------------------------------------------------------------------
# Data preservation and boundaries (T-DATA, credits, inactivity)
# ---------------------------------------------------------------------------

def test_seat_lifecycle_never_touches_members_work_or_credits(db):
    ns = seed(db.session)
    work = UserSession(
        user_id=ns.owner, session_id=f"p8-project-{ns.suffix}", name="Saved decision",
        organization_id=ns.org, payload={"chat_history": [{"role": "user", "content": "keep"}]},
    )
    db.session.add(work)
    db.session.commit()
    snapshot = (
        _members(db.session, ns.org),
        [(w.id, w.user_id, w.organization_id, w.payload, w.status) for w in db.session.query(UserSession).filter_by(organization_id=ns.org)],
        db.session.query(CreditLot).filter_by(billing_account_id=ns.account).count(),
        db.session.query(CreditLedgerEntry).filter_by(billing_account_id=ns.account).count(),
        db.session.get(Organization, ns.org).max_total_paid_seats,
    )
    change, _state = reduce(db.session, ns, "life", 3, ANCHOR + timedelta(days=1))
    mark_seat_renewal_unpaid(db.session, seat_change_id=change.id, observed_at=ns.renewal, actor_id="renewal", delivery_obligations=DELIVERIES)
    line = paid_line(db.session, ns.account, ns.subscription, "subscription", ns.renewal + timedelta(days=1), f"life-{ns.suffix}")
    renew(db.session, change.id, line, ns.renewal + timedelta(days=1))
    db.session.commit()
    assert current_seat_commitment(db.session, ns.subscription).quantity == 3
    after = (
        _members(db.session, ns.org),
        [(w.id, w.user_id, w.organization_id, w.payload, w.status) for w in db.session.query(UserSession).filter_by(organization_id=ns.org)],
        db.session.query(CreditLot).filter_by(billing_account_id=ns.account).count(),
        db.session.query(CreditLedgerEntry).filter_by(billing_account_id=ns.account).count(),
        db.session.get(Organization, ns.org).max_total_paid_seats,
    )
    assert after == snapshot


def test_seat_service_writes_no_membership_work_or_legacy_seat_state():
    source = (BACKEND_DIR / "app" / "billing_seats.py").read_text()
    for forbidden in (
        "OrganizationMember(", "max_total_paid_seats", "UserSession", "session.delete",
        "delete(", "Organization(", "credits_remaining", "CreditLot", "append_entry", "commit()",
    ):
        assert forbidden not in source, forbidden
    # No assignment to a membership role or status anywhere in the service.
    assert not re.search(r"\.(role|status)\s*=(?!=)", source)


def test_seat_service_has_no_live_runtime_callers():
    app_dir = BACKEND_DIR / "app"
    callers = [
        str(path.relative_to(BACKEND_DIR))
        for path in app_dir.rglob("*.py")
        # Phase 11 contract activation is itself inactive and reuses Phase 8 commitments;
        # Phase 13 projections are inactive and only read seat occupancy and commitments.
        if path.name not in {"billing_seats.py", "billing_enterprise_contracts.py", "models_billing_phase8.py", "models.py",
                             "billing_projections.py",
                             # I2 (D18 row 17): live only under BILLING_MODERN_FAMILIES (financial_events); off by default, refused in production.
                             "billing_runtime_financial.py"}
        and ("billing_seats" in path.read_text() or "models_billing_phase8" in path.read_text())
    ]
    assert callers == []


def test_sql_occupancy_roles_match_membership_authority():
    module = _revision()
    sql_roles = set(re.findall(r"'([a-z]+)'", module.PAID_ROLE_SQL))
    python_roles = {
        role for role in set(ORG_ROLES) | set(_ROLE_ALIAS)
        if normalize_org_role(role) in PAID_OCCUPANCY_ROLES
    }
    assert sql_roles == python_roles
    assert PAID_OCCUPANCY_ROLES == {"owner", "admin", "creator", "collaborator"}


# ---------------------------------------------------------------------------
# Migration shape, downgrade safety (SQLite and isolated PostgreSQL schema)
# ---------------------------------------------------------------------------

@contextlib.contextmanager
def _ops(engine):
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        with Operations.context(context):
            yield connection
        connection.commit()


_REVISION_MODULE = []


def _revision():
    if not _REVISION_MODULE:
        _REVISION_MODULE.append(ScriptDirectory(MIGRATIONS_DIR).get_revision(REVISION).module)
    return _REVISION_MODULE[0]


def _predecessor(engine):
    # Phase 11 tables are later than this revision and refer to its tables.
    phase11 = ("enterprise_contracts", "enterprise_contract_versions", "enterprise_contract_events", "enterprise_contract_term_fundings", "enterprise_contract_activations", "enterprise_contract_notices")
    tables = [t for t in flask_db.metadata.sorted_tables if t.name not in PHASE8_TABLES + phase11]
    flask_db.metadata.create_all(engine, tables=tables)


def _assert_models_match(engine):
    inspector = sa.inspect(engine)
    for model in (SeatCommitment, SeatChange, SeatChangeEvent, SeatCommitmentFence):
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
        model_indexes = {i.name for i in table.indexes}
        db_indexes = {i["name"] for i in inspector.get_indexes(table.name)}
        assert model_indexes <= db_indexes, table.name


def test_revision_extends_phase7_and_is_single_head():
    script = ScriptDirectory(MIGRATIONS_DIR)
    assert script.get_heads() == ["e7b9d1f3a5c6"]  # I2 follows I1, which follows BI-1; BI-1 extends the Phase 17 guard, which extends Phase 14 without changing Phase 8.
    assert script.get_revision("f2b4d6e8a0c3").down_revision == "e1a3c5b7d9f2"
    assert script.get_revision("e1a3c5b7d9f2").down_revision == REVISION
    assert script.get_revision(REVISION).down_revision == PARENT


def test_sqlite_migration_matches_models_and_downgrade_is_safe(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase8.sqlite'}")
    try:
        _predecessor(engine)
        with _ops(engine):
            _revision().upgrade()
        _assert_models_match(engine)
        with _ops(engine):
            _revision().downgrade()
        tables = set(sa.inspect(engine).get_table_names())
        assert not tables & set(PHASE8_TABLES) and "scheduled_plan_changes" in tables
        with _ops(engine):
            _revision().upgrade()
        with engine.begin() as connection:
            connection.execute(sa.text("PRAGMA foreign_keys=OFF"))
            connection.execute(sa.text(
                "INSERT INTO seat_commitments (id,billing_account_id,subscription_id,quantity,origin_type,"
                "state,starts_at,idempotency_registry_id,domain_event_id,created_at) "
                "VALUES ('c1','a','s',1,'opening','active','2026-01-31','r','e','2026-01-31')"
            ))
            with pytest.raises(sa.exc.DBAPIError):
                connection.execute(sa.text("DELETE FROM seat_commitments"))
        with pytest.raises(_revision().Phase8EvidenceNotEmptyError):
            with _ops(engine):
                _revision().downgrade()
        assert "seat_commitments" in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()


@pytest.mark.postgres
@PG
def test_postgres_isolated_migration_guards_and_downgrade_safety(validate_test_database_url, postgres_schema_url):
    base_url = validate_test_database_url(os.environ["TEST_DATABASE_URL"])
    schema = f"phase8_{uuid.uuid4().hex}"
    admin = sa.create_engine(base_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as connection:
        connection.execute(sa.text(f'CREATE SCHEMA "{schema}"'))
    engine = sa.create_engine(postgres_schema_url(base_url, schema))
    try:
        _predecessor(engine)
        with _ops(engine):
            _revision().upgrade()
        _assert_models_match(engine)
        with engine.connect() as connection:
            triggers = set(connection.execute(sa.text(
                "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
                "JOIN pg_namespace n ON n.oid=c.relnamespace "
                "WHERE NOT t.tgisinternal AND n.nspname=current_schema() AND t.tgname LIKE 'trg_phase8_%'"
            )).scalars())
        assert triggers == {name for name, _table in _revision().PG_TRIGGERS}
        with _ops(engine):
            _revision().downgrade()
        with engine.connect() as connection:
            leftover = connection.execute(sa.text(
                "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
                "WHERE n.nspname=current_schema() AND p.proname LIKE 'phase8_%'"
            )).scalar_one()
        assert leftover == 0
        assert not set(sa.inspect(engine).get_table_names()) & set(PHASE8_TABLES)
        with _ops(engine):
            _revision().upgrade()
        with engine.connect() as connection:
            with pytest.raises(sa.exc.DBAPIError):
                connection.execute(sa.text("TRUNCATE seat_change_events"))
            connection.rollback()
            connection.execute(sa.text("SET session_replication_role = replica"))
            connection.execute(sa.text(
                "INSERT INTO seat_commitments (id,billing_account_id,subscription_id,quantity,origin_type,"
                "state,starts_at,idempotency_registry_id,domain_event_id) "
                "VALUES ('c1','a','s',1,'opening','active',now(),'r','e')"
            ))
            connection.commit()
        with pytest.raises(_revision().Phase8EvidenceNotEmptyError):
            with _ops(engine):
                _revision().downgrade()
        assert "seat_commitments" in sa.inspect(engine).get_table_names()
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
    engine = sa.create_engine(url, pool_size=6, max_overflow=4)
    with engine.connect() as connection:
        revision = connection.execute(sa.text("SELECT version_num FROM alembic_version")).scalar_one_or_none()
    if revision not in {REVISION, "e1a3c5b7d9f2", "f2b4d6e8a0c3", "b4d6f8a0c2e5", "c8e0a2b4d6f1", "d2f4a6c8e0b3", "f3a5c7e9b1d2", "c8a9989843b5", "a1f3c5e7b9d0", "e7b9d1f3a5c6"}:
        engine.dispose()
        pytest.fail(f"Phase 8 migrated tests require Alembic head {REVISION}; found {revision!r}")
    return engine


@pytest.mark.postgres
@PG
def test_postgres_migrated_full_lifecycle_passes_guards():
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed(session, extra_roles=("admin", "creator", "collaborator"))  # occupancy 4
            paid_at = ANCHOR + timedelta(days=10)
            line = paid_line(session, ns.account, ns.subscription, "seat", paid_at, f"pg-inc-{ns.suffix}")
            session.commit()
            change, commitment, state = increase(session, ns, "pg-add", 2, line, paid_at)
            session.commit()
            assert state == "inserted" and commitment.quantity == 7
            assert increase(session, ns, "pg-add", 2, line, paid_at)[2] == "duplicate"
            session.commit()
            blocked, state = reduce(session, ns, "pg-red", 3, paid_at + timedelta(hours=1))
            session.commit()
            assert blocked.state == "blocked_occupancy"
            assert reevaluate_blocked_reduction(
                session, seat_change_id=blocked.id, evaluated_at=paid_at + timedelta(hours=2),
                requested_by_user_id=ns.badmin, delivery_obligations=DELIVERIES,
            )[1] == "still_blocked"
            session.commit()
            member = session.query(OrganizationMember).filter_by(organization_id=ns.org, role="collaborator").one()
            member.status = "removed"
            session.commit()
            resolved, state = reevaluate_blocked_reduction(
                session, seat_change_id=blocked.id, evaluated_at=paid_at + timedelta(hours=3),
                requested_by_user_id=ns.badmin, delivery_obligations=DELIVERIES,
            )
            session.commit()
            assert resolved.state == "scheduled_reduction"
            record_seat_change_approaching(
                session, seat_change_id=blocked.id, observed_at=paid_at + timedelta(days=1),
                delivery_obligations=DELIVERIES,
            )
            mark_seat_renewal_unpaid(
                session, seat_change_id=blocked.id, observed_at=ns.renewal,
                actor_id="renewal", delivery_obligations=DELIVERIES,
            )
            session.commit()
            late = ns.renewal + timedelta(days=2)
            renewal = paid_line(session, ns.account, ns.subscription, "subscription", late, f"pg-ren-{ns.suffix}")
            session.commit()
            applied, reduced, state = renew(session, blocked.id, renewal, late)
            session.commit()
            assert state == "inserted" and applied.state == "reduced" and reduced.quantity == 3
            assert renew(session, blocked.id, renewal, late)[2] == "duplicate"
            session.commit()
            chain = session.query(SeatCommitment).filter_by(subscription_id=ns.subscription).count()
            assert chain == 3
            cancelled_ns = seed(session)
            pending, _ = reduce(session, cancelled_ns, "pg-cancel", 4, ANCHOR + timedelta(days=1))
            session.commit()
            cancel_seat_change(
                session, seat_change_id=pending.id, cancelled_at=ANCHOR + timedelta(days=2),
                requested_by_user_id=cancelled_ns.payer, delivery_obligations=DELIVERIES,
            )
            session.commit()
            assert session.get(SeatChange, pending.id).state == "cancelled"
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
            ns = seed(session)
            change, _ = reduce(session, ns, "pg-bypass", 4, ANCHOR + timedelta(days=1))
            session.commit()
            p = {"id": ns.opening, "change": change.id, "sub": ns.subscription, "account": ns.account}
            _raises_integrity(session, "UPDATE seat_commitments SET quantity=99 WHERE id=:id", p)
            _raises_integrity(session, "DELETE FROM seat_commitments WHERE id=:id", p)
            _raises_integrity(session, "UPDATE seat_changes SET state='reduced' WHERE id=:change", p)
            _raises_integrity(session, "UPDATE seat_changes SET target_quantity=1 WHERE id=:change", p)
            _raises_integrity(session, "DELETE FROM seat_changes WHERE id=:change", p)
            _raises_integrity(session, "TRUNCATE seat_changes CASCADE")
            # Closing a commitment without a successor fails at commit.
            _raises_integrity(session, "UPDATE seat_commitments SET state='replaced', ends_at=now() WHERE id=:id", p)
            # A direct opening without registry/event/payment evidence.
            _raises_integrity(session, """
                INSERT INTO seat_commitments (id,billing_account_id,subscription_id,quantity,origin_type,
                  state,starts_at,idempotency_registry_id,domain_event_id)
                SELECT 'p8-direct-'||:sub,billing_account_id,subscription_id,9,'increase','active',now(),
                  idempotency_registry_id,domain_event_id
                FROM seat_commitments WHERE id=:id
            """, p)
            # A system actor cannot cancel; a renewal transition needs a system actor.
            event_row = session.execute(sa.text(
                "SELECT idempotency_registry_id, domain_event_id FROM seat_changes WHERE id=:change"), p).one()
            for to_state, actor_type, grant in (
                ("cancelled", "system", None),
                ("awaiting_payment", "user", f"p8-grant-badmin-{ns.suffix}"),
            ):
                _raises_integrity(session, """
                    INSERT INTO seat_change_events (id,seat_change_id,from_state,to_state,transition,effective_at,
                      actor_type,actor_id,authorizing_role_grant_id,evidence_json,idempotency_registry_id,domain_event_id)
                    VALUES (:eid,:change,'scheduled_reduction',:to,'direct',now(),:actor,'x',:grant,'{}',:reg,:evt)
                """, {**p, "eid": f"p8-direct-evt-{uuid.uuid4().hex[:8]}", "to": to_state, "actor": actor_type,
                      "grant": grant, "reg": event_row[0], "evt": event_row[1]})
            # Immutable events.
            mark_seat_renewal_unpaid(
                session, seat_change_id=change.id, observed_at=ns.renewal,
                actor_id="renewal", delivery_obligations=DELIVERIES,
            )
            session.commit()
            _raises_integrity(session, "UPDATE seat_change_events SET actor_id='rewritten' WHERE seat_change_id=:change", p)
            _raises_integrity(session, "DELETE FROM seat_change_events WHERE seat_change_id=:change", p)
            assert session.get(SeatChange, change.id).state == "awaiting_payment"
    finally:
        engine.dispose()


@pytest.mark.postgres
@PG
def test_postgres_guard_enforces_occupancy_on_direct_reduction():
    """With valid permission and evidence, the database still checks occupancy."""
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed(session, extra_roles=("admin", "creator", "collaborator"))  # occupancy 4
            for state, occupancy, grant in (
                ("scheduled_reduction", 4, "badmin"),   # occupancy 4 > target 3 must be blocked
                ("scheduled_reduction", 2, "badmin"),   # misreported occupancy
                ("blocked_occupancy", 2, "badmin"),     # misreported occupancy
                ("blocked_occupancy", 4, "bviewer"),    # honest facts, viewer permission
                ("blocked_occupancy", 4, "owner"),      # organization owner has no billing grant
            ):
                session.rollback()
                cid = str(uuid.uuid4())
                key = f"seat:{ns.org}:direct-{cid}"
                event_type = "seat_reduction_blocked" if state == "blocked_occupancy" else "seat_change_scheduled"
                registry, _ = _claim_registry(session, "seat_command", key, "f" * 64, ANCHOR)
                event, _m, _s = record_domain_event(session, {
                    "billing_account_id": ns.account, "event_key": f"{event_type}:{cid}:created",
                    "event_type": event_type, "aggregate_type": "seat_change",
                    "aggregate_id": cid, "occurred_at": ANCHOR, "reference_ids": [cid],
                }, DELIVERIES)
                with pytest.raises(sa.exc.DBAPIError):
                    session.execute(sa.text("""
                        INSERT INTO seat_changes (id,billing_account_id,subscription_id,kind,state,base_commitment_id,
                          base_quantity,target_quantity,occupancy_at_request,requested_at,effective_at,
                          authorizing_role_grant_id,requested_by_user_id,command_key,request_fingerprint,
                          idempotency_registry_id,domain_event_id)
                        VALUES (:cid,:account,:sub,'reduction',:state,:base,5,3,:occ,:at,:eff,:grant,:user,:key,:fp,:reg,:evt)
                    """), {"cid": cid, "account": ns.account, "sub": ns.subscription, "state": state,
                           "base": ns.opening, "occ": occupancy, "at": ANCHOR, "eff": ns.renewal,
                           "grant": f"p8-grant-{grant}-{ns.suffix}",
                           "user": getattr(ns, grant, ns.owner), "key": key, "fp": "f" * 64,
                           "reg": registry.id, "evt": event.id})
                session.rollback()
            # The same shape with the true occupancy and state is accepted.
            change, _ = reduce(session, ns, "honest", 3, ANCHOR + timedelta(days=1))
            session.commit()
            assert change.state == "blocked_occupancy"
    finally:
        engine.dispose()


def _race(engine, isolation_level, workers):
    worker_engine = engine.execution_options(isolation_level=isolation_level)
    barrier = threading.Barrier(len(workers))

    def run(work):
        with Session(worker_engine, expire_on_commit=False) as session:
            barrier.wait(timeout=10)
            try:
                result = work(session)
                session.commit()
                return result
            except SeatChangeConflictError:
                session.rollback()
                return "conflict"
            except sa.exc.DBAPIError as exc:
                session.rollback()
                code = getattr(exc.orig, "sqlstate", None)
                if code in {"23505", "40001", "40P01"}:
                    return code
                raise

    with ThreadPoolExecutor(max_workers=len(workers)) as pool:
        return list(pool.map(run, workers))


ISOLATION = pytest.mark.parametrize("isolation_level", ("READ COMMITTED", "REPEATABLE READ", "SERIALIZABLE"))


@pytest.mark.postgres
@PG
@ISOLATION
def test_postgres_concurrent_paid_increases_each_add_their_paid_seats(isolation_level):
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed(session)
            paid_at = ANCHOR + timedelta(days=4)
            lines = [paid_line(session, ns.account, ns.subscription, "seat", paid_at, f"race{i}-{ns.suffix}") for i in range(2)]
            session.commit()
        outcomes = _race(engine, isolation_level, [
            (lambda s, i=i: increase(s, ns, f"race-{i}", i + 1, lines[i], paid_at)[2]) for i in range(2)
        ])
        assert set(outcomes) <= {"inserted", "40001", "40P01"} and "inserted" in outcomes
        expected = 5 + sum(i + 1 for i, outcome in enumerate(outcomes) if outcome == "inserted")
        with Session(engine) as verify:
            assert current_seat_commitment(verify, ns.subscription).quantity == expected
            assert verify.query(SeatCommitment).filter_by(subscription_id=ns.subscription, state="active").count() == 1
    finally:
        engine.dispose()


@pytest.mark.postgres
@PG
@ISOLATION
def test_postgres_duplicate_increase_commands_converge(isolation_level):
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed(session)
            paid_at = ANCHOR + timedelta(days=4)
            line = paid_line(session, ns.account, ns.subscription, "seat", paid_at, f"dup-{ns.suffix}")
            session.commit()
        outcomes = _race(engine, isolation_level, [
            (lambda s: increase(s, ns, "same-command", 1, line, paid_at)[2]) for _ in range(2)
        ])
        assert outcomes.count("inserted") == 1
        assert set(outcomes) <= {"inserted", "duplicate", "40001", "40P01", "23505"}
        with Session(engine) as verify:
            assert current_seat_commitment(verify, ns.subscription).quantity == 6
            assert verify.query(SeatChange).filter_by(subscription_id=ns.subscription).count() == 1
    finally:
        engine.dispose()


@pytest.mark.postgres
@PG
@pytest.mark.parametrize("isolation_level", ("READ COMMITTED",))
def test_postgres_competing_reductions_keep_one_active(isolation_level):
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed(session)
        at = ANCHOR + timedelta(days=1)
        outcomes = _race(engine, isolation_level, [
            (lambda s, i=i: reduce(s, ns, f"compete-{i}", 4 - i, at)[1]) for i in range(2)
        ])
        assert outcomes.count("inserted") == 1
        assert set(outcomes) <= {"inserted", "conflict", "23505", "40001", "40P01"}
        with Session(engine) as verify:
            active = verify.query(SeatChange).filter(
                SeatChange.subscription_id == ns.subscription,
                SeatChange.state.in_(("scheduled_reduction", "blocked_occupancy", "awaiting_payment")),
            ).count()
            assert active == 1
    finally:
        engine.dispose()


@pytest.mark.postgres
@PG
@pytest.mark.parametrize("isolation_level", ("READ COMMITTED",))
def test_postgres_increase_racing_reduction_resolves_by_precedence(isolation_level):
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed(session)
            paid_at = ANCHOR + timedelta(days=4)
            line = paid_line(session, ns.account, ns.subscription, "seat", paid_at, f"mix-{ns.suffix}")
            session.commit()
        outcomes = _race(engine, isolation_level, [
            lambda s: increase(s, ns, "mix-inc", 1, line, paid_at)[2],
            lambda s: reduce(s, ns, "mix-red", 4, paid_at)[1],
        ])
        with Session(engine) as verify:
            changes = {c.kind: c for c in verify.query(SeatChange).filter_by(subscription_id=ns.subscription)}
            commitment = current_seat_commitment(verify, ns.subscription)
            if "increase" in changes:
                assert commitment.quantity == 6
            if "increase" in changes and "reduction" in changes:
                reduction, inc = changes["reduction"], changes["increase"]
                if inc.supersedes_change_id == reduction.id:
                    assert reduction.state == "superseded"
                else:
                    # Reduction recorded after the increase, against the new commitment.
                    assert reduction.base_commitment_id == commitment.id
            assert verify.query(SeatCommitment).filter_by(subscription_id=ns.subscription, state="active").count() == 1
        assert set(outcomes) <= {"inserted", "conflict", "40001", "40P01", "23505"}
    finally:
        engine.dispose()



# ===========================================================================
# Audit remediation: H1 payment evidence, H2 occupancy concurrency,
# H3 actor authorization, M1 SQLite append-only protections
# ===========================================================================

# ---- H1 -------------------------------------------------------------------

def test_h1_payment_line_authorizes_at_most_one_seat_effect(db):
    """Auditor probe: the opening's seat payment cannot also fund an increase."""
    ns = seed(db.session)
    before = _counts(db.session, ns.account)
    # One attribution per line: the opening line cannot be re-attributed.
    with pytest.raises(SeatChangeConflictError):
        attribute(db.session, ns.subscription, ns.seat_line, "purchased", ANCHOR, ns.renewal, seats=1)
    db.session.rollback()
    # And an attribution already used by the opening cannot fund an increase.
    with pytest.raises(SeatFundingError, match="already been used"):
        increase(db.session, ns, "reuse-opening", 2, None, ANCHOR, attribution_ids=[ns.opening_attributions[1]])
    db.session.rollback()
    assert _counts(db.session, ns.account) == before
    assert current_seat_commitment(db.session, ns.subscription).quantity == 5


def test_h1_blocked_renewal_payment_cannot_later_authorize_a_reduction(db):
    """Auditor probe: renewal evidence consumed by a blocked decision is spent."""
    ns = seed(db.session)  # occupancy 3
    first, _ = reduce(db.session, ns, "first", 3, ANCHOR + timedelta(days=1))
    add_member(db.session, ns.org, _user(db.session, ns.suffix, "late").id, "creator")
    line = paid_line(db.session, ns.account, ns.subscription, "subscription", ns.renewal, f"blk-{ns.suffix}")
    db.session.commit()
    _change, _commitment, state = renew(db.session, first.id, line, ns.renewal)
    db.session.commit()
    assert state == "blocked"
    cancel_seat_change(
        db.session, seat_change_id=first.id, cancelled_at=ns.renewal,
        requested_by_user_id=ns.badmin, delivery_obligations=DELIVERIES,
    )
    late = db.session.query(OrganizationMember).filter_by(user_id=f"p8-late-{ns.suffix}").one()
    late.status = "removed"
    db.session.commit()
    second, _ = reduce(db.session, ns, "second", 4, ANCHOR + timedelta(days=2))
    db.session.commit()
    assert second.state == "scheduled_reduction"
    with pytest.raises(SeatFundingError, match="already been used"):
        renew(db.session, second.id, line, ns.renewal)
    db.session.rollback()
    assert current_seat_commitment(db.session, ns.subscription).quantity == 5


def test_h1_sequential_reductions_cannot_share_one_renewal(db):
    """Auditor probe: a second reduction cannot be backdated onto a used renewal."""
    ns = seed(db.session)
    first, _ = reduce(db.session, ns, "first", 4, ANCHOR + timedelta(days=1))
    line = paid_line(db.session, ns.account, ns.subscription, "subscription", ns.renewal, f"seq-{ns.suffix}")
    db.session.commit()
    _c, reduced, _s = renew(db.session, first.id, line, ns.renewal)
    db.session.commit()
    assert reduced.quantity == 4
    # The term has not been advanced; a backdated request against the new
    # interval is refused, so the same renewal cannot reduce twice.
    with pytest.raises(SeatChangeError):
        reduce(db.session, ns, "second", 3, ANCHOR + timedelta(days=2))
    db.session.rollback()
    assert current_seat_commitment(db.session, ns.subscription).quantity == 4


def test_h1_payment_correspondence_currency_and_account(db):
    ns = seed(db.session)
    other = seed(db.session)
    paid_at = ANCHOR + timedelta(days=3)
    eur = paid_line(db.session, ns.account, ns.subscription, "seat", paid_at, f"eur-{ns.suffix}", currency="eur")
    foreign = paid_line(db.session, other.account, other.subscription, "seat", paid_at, f"fx-{other.suffix}")
    db.session.commit()
    for command, line in (("eur", eur), ("foreign", foreign)):
        with pytest.raises(SeatChangeError):
            increase(db.session, ns, command, 1, line, paid_at)
        db.session.rollback()


def test_h1_quantity_mismatch_probe(db):
    """Auditor probe: one funded seat cannot support a ten-seat increase.

    Seats come from the funding attribution, never from FinancialLine.quantity.
    """
    ns = seed(db.session)
    paid_at = ANCHOR + timedelta(days=3)
    line = paid_line(db.session, ns.account, ns.subscription, "seat", paid_at, f"q-{ns.suffix}", quantity=10)
    db.session.commit()
    with pytest.raises(SeatFundingError, match="exactly the added seats"):
        increase(db.session, ns, "ten-for-one", 10, line, paid_at, seats=1)
    db.session.rollback()
    assert current_seat_commitment(db.session, ns.subscription).quantity == 5


# ---- H3 (service) -----------------------------------------------------------

def test_h3_grant_ended_before_now_cannot_be_backdated(db):
    ns = seed(db.session)
    grant = db.session.get(BillingRoleGrant, f"p8-grant-badmin-{ns.suffix}")
    grant.ends_at = ANCHOR + timedelta(days=5)  # still "active" by state, but over
    db.session.commit()
    with pytest.raises(SeatChangePermissionError):
        reduce(db.session, ns, "backdated", 4, ANCHOR + timedelta(days=1))
    db.session.rollback()
    change, _ = reduce(db.session, ns, "current", 4, ANCHOR + timedelta(days=1), user=ns.payer)
    db.session.commit()
    assert change.requested_by_user_id == ns.payer
    assert db.session.get(BillingRoleGrant, change.authorizing_role_grant_id).user_id == ns.payer


# ---- M1: migrated SQLite append-only protections -----------------------------

def test_m1_sqlite_migrated_service_paths_work_and_direct_mutation_is_refused(tmp_path):
    engine = sa.create_engine(f"sqlite:///{tmp_path / 'phase8-m1.sqlite'}")
    try:
        _predecessor(engine)
        with _ops(engine):
            _revision().upgrade()
        with Session(engine, expire_on_commit=False) as session:
            ns = seed(session, extra_roles=("admin", "creator", "collaborator"))
            paid_at = ANCHOR + timedelta(days=4)
            line = paid_line(session, ns.account, ns.subscription, "seat", paid_at, f"m1-{ns.suffix}")
            session.commit()
            inc, _commitment, _state = increase(session, ns, "m1-inc", 1, line, paid_at)
            session.commit()
            blocked, _ = reduce(session, ns, "m1-red", 3, paid_at + timedelta(hours=1))
            session.commit()
            assert blocked.state == "blocked_occupancy"
            member = session.query(OrganizationMember).filter_by(organization_id=ns.org, role="collaborator").one()
            member.status = "removed"
            session.commit()
            resolved, _ = reevaluate_blocked_reduction(
                session, seat_change_id=blocked.id, evaluated_at=paid_at + timedelta(hours=2),
                requested_by_user_id=ns.badmin, delivery_obligations=DELIVERIES,
            )
            session.commit()
            assert resolved.state == "scheduled_reduction"
            mark_seat_renewal_unpaid(
                session, seat_change_id=blocked.id, observed_at=ns.renewal,
                actor_id="renewal", delivery_obligations=DELIVERIES,
            )
            renewal = paid_line(session, ns.account, ns.subscription, "subscription", ns.renewal, f"m1r-{ns.suffix}")
            session.commit()
            _c, reduced, state = renew(session, blocked.id, renewal, ns.renewal)
            session.commit()
            assert state == "inserted" and reduced.quantity == 3
            ids = {"c": reduced.id, "old": ns.opening, "x": blocked.id, "i": inc.id}
        statements = (
            "UPDATE seat_commitments SET quantity=99 WHERE id=:c",
            "UPDATE seat_commitments SET state='active', ends_at=NULL WHERE id=:old",
            "UPDATE seat_commitments SET ends_at='2030-01-01' WHERE id=:old",
            "UPDATE seat_funding_attributions SET seats=99",
            "UPDATE seat_term_fundings SET funded_seats=0",
            "UPDATE seat_funding_uses SET term_funding_id='other'",
            "DELETE FROM seat_funding_uses",
            "DELETE FROM seat_term_fundings",
            "DELETE FROM seat_funding_attributions",
            "UPDATE seat_changes SET target_quantity=1 WHERE id=:x",
            "UPDATE seat_changes SET requested_by_user_id='someone-else' WHERE id=:i",
            "UPDATE seat_changes SET authorizing_role_grant_id='other-grant' WHERE id=:i",
            "UPDATE seat_changes SET state='cancelled' WHERE id=:x",
            "UPDATE seat_changes SET effective_at='2031-01-01' WHERE id=:x",
            "UPDATE seat_change_events SET actor_id='rewritten' WHERE seat_change_id=:x",
            "DELETE FROM seat_change_events WHERE seat_change_id=:x",
            "DELETE FROM seat_changes WHERE id=:i",
            "DELETE FROM seat_commitments WHERE id=:old",
            "DELETE FROM seat_commitment_fences",
        )
        for statement in statements:
            with engine.begin() as connection:
                if "fences" in statement:
                    connection.execute(sa.text("INSERT INTO seat_commitment_fences (subscription_id) VALUES ('f1')"))
                with pytest.raises(sa.exc.DBAPIError):
                    connection.execute(sa.text(statement), ids)
        with Session(engine) as verify:
            assert verify.get(SeatCommitment, ids["c"]).quantity == 3
            assert verify.get(SeatChange, ids["x"]).state == "reduced"
            assert sorted(e.to_state for e in verify.query(SeatChangeEvent).filter_by(seat_change_id=ids["x"])) == ["awaiting_payment", "reduced", "scheduled_reduction"]
    finally:
        engine.dispose()


# ---- H2 (PostgreSQL) ----------------------------------------------------------

def _member_writer(engine, statement, params, started, release):
    """A live-style membership writer in its own READ COMMITTED transaction."""
    with engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(sa.text(statement), params)
        started.set()
        release.wait(timeout=20)
        transaction.commit()
        return datetime.now(timezone.utc)


def _scheduled_case(session, roles=("admin", "creator")):
    ns = seed(session, extra_roles=roles)  # occupancy 1 + len(paid roles)
    change, _ = reduce(session, ns, "h2", 3, ANCHOR + timedelta(days=1))
    renewal = paid_line(session, ns.account, ns.subscription, "subscription", ns.renewal, f"h2-{ns.suffix}")
    session.commit()
    return ns, change, renewal


@pytest.mark.postgres
@PG
@pytest.mark.parametrize("membership_change", ("insert_member", "promote_viewer"))
def test_h2_reduction_waits_for_and_sees_concurrent_membership_increase(membership_change):
    """Auditor scenario: a membership increase in flight when the reduction decides."""
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns, change, renewal = _scheduled_case(session, roles=("admin", "creator", "viewer"))
            joiner = _user(session, ns.suffix, "joiner")
            session.commit()
        assert change.state == "scheduled_reduction"  # occupancy 3 <= 3
        if membership_change == "insert_member":
            statement = ("INSERT INTO organization_members (organization_id,user_id,role,status,created_at,updated_at) "
                         "VALUES (:org,:user,'collaborator','active',now(),now())")
            params = {"org": ns.org, "user": joiner.id}
        else:
            statement = "UPDATE organization_members SET role='creator' WHERE organization_id=:org AND role='viewer'"
            params = {"org": ns.org}
        started, release = threading.Event(), threading.Event()
        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(_member_writer, engine, statement, params, started, release)
            assert started.wait(timeout=10)

            def apply():
                with Session(engine, expire_on_commit=False) as session:
                    result = renew(session, change.id, renewal, ns.renewal)
                    session.commit()
                    return result[2]

            reducer = pool.submit(apply)
            # The reduction cannot decide while the membership change is open.
            with pytest.raises(Exception):
                reducer.result(timeout=1.0)
            release.set()
            writer.result(timeout=10)
            assert reducer.result(timeout=20) == "blocked"
        with Session(engine) as verify:
            assert current_seat_commitment(verify, ns.subscription).quantity == 5
            assert seat_occupancy(verify, ns.org) == 4
    finally:
        engine.dispose()


@pytest.mark.postgres
@PG
def test_h2_membership_increase_waits_for_an_open_reduction_decision():
    """Reverse order: a membership writer arriving after the decision commits after it."""
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns, change, renewal = _scheduled_case(session)
            joiner = _user(session, ns.suffix, "joiner")
            session.commit()
        holder = Session(engine, expire_on_commit=False)
        try:
            _c, reduced, state = renew(holder, change.id, renewal, ns.renewal)
            assert state == "inserted" and reduced.quantity == 3
            started, release = threading.Event(), threading.Event()
            release.set()
            with ThreadPoolExecutor(max_workers=1) as pool:
                writer = pool.submit(
                    _member_writer, engine,
                    "INSERT INTO organization_members (organization_id,user_id,role,status,created_at,updated_at) "
                    "VALUES (:org,:user,'collaborator','active',now(),now())",
                    {"org": ns.org, "user": joiner.id}, started, release,
                )
                with pytest.raises(Exception):
                    writer.result(timeout=1.0)  # blocked behind the reduction's locks
                holder.commit()
                reduction_committed = datetime.now(timezone.utc)
                writer_committed = writer.result(timeout=10)
            assert writer_committed >= reduction_committed
        finally:
            holder.close()
    finally:
        engine.dispose()


@pytest.mark.postgres
@PG
@pytest.mark.parametrize("isolation_level", ("REPEATABLE READ", "SERIALIZABLE"))
def test_h2_stale_snapshot_isolation_fails_closed(isolation_level):
    """Auditor scenario under snapshot isolation: refuse rather than decide stale."""
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns, change, renewal = _scheduled_case(session)
            joiner = _user(session, ns.suffix, "joiner")
            blocked_ns = seed(session, extra_roles=("admin", "creator", "collaborator"))
            blocked, _ = reduce(session, blocked_ns, "blocked", 3, ANCHOR + timedelta(days=1))
            session.commit()
        worker = engine.execution_options(isolation_level=isolation_level)
        with Session(worker, expire_on_commit=False) as stale:
            stale.execute(sa.text("SELECT 1 FROM organization_members LIMIT 1"))  # snapshot taken
            with engine.begin() as connection:
                connection.execute(sa.text(
                    "INSERT INTO organization_members (organization_id,user_id,role,status,created_at,updated_at) "
                    "VALUES (:org,:user,'collaborator','active',now(),now())"), {"org": ns.org, "user": joiner.id})
            before = (_counts(stale, ns.account), _counts(stale, blocked_ns.account))
            for attempt in (
                lambda: renew(stale, change.id, renewal, ns.renewal),
                lambda: reduce(stale, ns, "stale-request", 4, ANCHOR + timedelta(days=2), supersede=True),
                lambda: reevaluate_blocked_reduction(stale, seat_change_id=blocked.id,
                                                     evaluated_at=ANCHOR + timedelta(days=2),
                                                     requested_by_user_id=blocked_ns.badmin,
                                                     delivery_obligations=DELIVERIES),
            ):
                with pytest.raises(SeatChangeIsolationError):
                    attempt()
                stale.rollback()
            assert (_counts(stale, ns.account), _counts(stale, blocked_ns.account)) == before
        with Session(engine) as verify:
            assert verify.get(SeatChange, change.id).state == "scheduled_reduction"
            assert current_seat_commitment(verify, ns.subscription).quantity == 5
    finally:
        engine.dispose()


# ---- H1/H3 direct SQL (PostgreSQL) --------------------------------------------

def _direct_reduction(session, ns, *, grant_id, user_id, account=None, occupancy=3, state="scheduled_reduction",
                      requested_at=None, organization=None):
    """Insert a reduction row with otherwise-valid claim/event evidence."""
    cid = str(uuid.uuid4())
    account = account or ns.account
    key = f"seat:{organization or ns.org}:direct-{cid}"
    event_type = "seat_reduction_blocked" if state == "blocked_occupancy" else "seat_change_scheduled"
    registry, _ = _claim_registry(session, "seat_command", key, "c" * 64, ANCHOR)
    event, _m, _s = record_domain_event(session, {
        "billing_account_id": account, "event_key": f"{event_type}:{cid}:created",
        "event_type": event_type, "aggregate_type": "seat_change", "aggregate_id": cid,
        "occurred_at": ANCHOR, "reference_ids": [cid],
    }, DELIVERIES)
    session.execute(sa.text("""
        INSERT INTO seat_changes (id,billing_account_id,subscription_id,kind,state,base_commitment_id,
          base_quantity,target_quantity,occupancy_at_request,requested_at,effective_at,
          authorizing_role_grant_id,requested_by_user_id,command_key,request_fingerprint,
          idempotency_registry_id,domain_event_id)
        VALUES (:cid,:account,:sub,'reduction',:state,:base,5,3,:occ,:at,:eff,:grant,:user,:key,:fp,:reg,:evt)
    """), {"cid": cid, "account": account, "sub": ns.subscription, "state": state, "base": ns.opening,
           "occ": occupancy, "at": requested_at or ANCHOR + timedelta(days=1), "eff": ns.renewal,
           "grant": grant_id, "user": user_id, "key": key, "fp": "c" * 64,
           "reg": registry.id, "evt": event.id})
    session.flush()


@pytest.mark.postgres
@PG
def test_h3_direct_sql_requires_the_grant_holder_for_this_account():
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed(session)  # occupancy 3, target 3 -> scheduled is the honest state
            other = seed(session)
            session.execute(sa.text(
                "UPDATE billing_role_grants SET ends_at=:end WHERE id=:id"),
                {"end": ANCHOR + timedelta(days=5), "id": f"p8-grant-payer-{ns.suffix}"})
            session.commit()
            badmin = f"p8-grant-badmin-{ns.suffix}"
            cases = {
                "impersonation": dict(grant_id=badmin, user_id=ns.payer),
                "null_actor": dict(grant_id=badmin, user_id=None),
                "viewer_grant": dict(grant_id=f"p8-grant-bviewer-{ns.suffix}", user_id=ns.bviewer),
                "other_org_grant": dict(grant_id=f"p8-grant-badmin-{other.suffix}", user_id=other.badmin),
                "other_org_account": dict(grant_id=f"p8-grant-badmin-{other.suffix}", user_id=other.badmin,
                                          account=other.account, organization=other.org),
                "backdated_into_ended_grant": dict(grant_id=f"p8-grant-payer-{ns.suffix}", user_id=ns.payer),
            }
            for name, kwargs in cases.items():
                with pytest.raises(sa.exc.DBAPIError, match=r".*"):
                    _direct_reduction(session, ns, **kwargs)
                    session.commit()
                session.rollback()
            # The honest row is accepted, proving each refusal above is the actor rule.
            _direct_reduction(session, ns, grant_id=badmin, user_id=ns.badmin)
            session.commit()
            honest = session.query(SeatChange).filter_by(subscription_id=ns.subscription).one()
            assert honest.requested_by_user_id == ns.badmin
            # A user transition naming another user's grant is refused.
            event_row = session.execute(sa.text(
                "SELECT id FROM seat_changes WHERE subscription_id=:sub"), {"sub": ns.subscription}).scalar_one()
            registry, _ = _claim_registry(
                session, "seat_transition", f"seat-transition:{event_row}:created:cancelled", "d" * 64, ANCHOR)
            dom, _m, _s = record_domain_event(session, {
                "billing_account_id": ns.account, "event_key": f"seat_change_cancelled:{event_row}:created:cancelled",
                "event_type": "seat_change_cancelled", "aggregate_type": "seat_change", "aggregate_id": event_row,
                "occurred_at": ANCHOR + timedelta(days=2), "reference_ids": [event_row],
            }, DELIVERIES)
            with pytest.raises(sa.exc.DBAPIError):
                session.execute(sa.text("""
                    INSERT INTO seat_change_events (id,seat_change_id,from_state,to_state,transition,effective_at,
                      actor_type,actor_id,authorizing_role_grant_id,evidence_json,idempotency_registry_id,domain_event_id)
                    VALUES (:id,:x,'scheduled_reduction','cancelled','direct',:at,'user',:actor,:grant,'{}',:reg,:evt)
                """), {"id": str(uuid.uuid4()), "x": event_row, "at": ANCHOR + timedelta(days=2),
                       "actor": ns.payer, "grant": badmin, "reg": registry.id, "evt": dom.id})
                session.commit()
            session.rollback()
    finally:
        engine.dispose()


@pytest.mark.postgres
@PG
def test_h1_direct_sql_rejects_funding_reuse_and_unfunded_commitments():
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed(session)
            first, _ = reduce(session, ns, "first", 4, ANCHOR + timedelta(days=1))
            line = paid_line(session, ns.account, ns.subscription, "subscription", ns.renewal, f"pgr-{ns.suffix}")
            session.commit()
            _c, reduced, _s = renew(session, first.id, line, ns.renewal)
            session.commit()
            funding = session.query(SeatTermFunding).filter_by(commitment_id=reduced.id).one()
            used = session.query(SeatFundingUse).filter_by(term_funding_id=funding.id).first()
            p = {"id": reduced.id, "new": str(uuid.uuid4()), "at": ns.renewal + timedelta(days=1),
                 "use": str(uuid.uuid4()), "attr": used.attribution_id, "f": funding.id,
                 "opening_funding": session.query(SeatTermFunding).filter_by(commitment_id=ns.opening).one().id}
            # A used attribution cannot be attached to another funding decision.
            _raises_integrity(session, "INSERT INTO seat_funding_uses (id,attribution_id,term_funding_id) "
                                       "VALUES (:use,:attr,:opening_funding)", p)
            # A new commitment interval without a funded term decision fails at commit.
            _raises_integrity(session, """
                UPDATE seat_commitments SET state='replaced', ends_at=:at WHERE id=:id;
                INSERT INTO seat_commitments (id,billing_account_id,subscription_id,quantity,origin_type,state,
                  starts_at,previous_commitment_id,idempotency_registry_id,domain_event_id)
                SELECT :new,billing_account_id,subscription_id,2,'reduction','active',:at,id,
                  idempotency_registry_id,domain_event_id FROM seat_commitments WHERE id=:id
            """, p)
            # Funding records and attributions are immutable.
            for statement in (
                "UPDATE seat_term_fundings SET funded_seats=funded_seats WHERE id=:f",
                "DELETE FROM seat_term_fundings WHERE id=:f",
                "UPDATE seat_funding_attributions SET seats=seats+1 WHERE id=:attr",
                "DELETE FROM seat_funding_uses WHERE attribution_id=:attr",
                "TRUNCATE seat_funding_attributions CASCADE",
            ):
                _raises_integrity(session, statement, p)
            assert current_seat_commitment(session, ns.subscription).quantity == 4
    finally:
        engine.dispose()


# ===========================================================================
# Founder-approved funding contract and purchasing authority
# ===========================================================================

def _funding(session, commitment_id, purpose=None):
    query = session.query(SeatTermFunding).filter_by(commitment_id=commitment_id)
    if purpose:
        query = query.filter_by(purpose=purpose)
    return query.order_by(SeatTermFunding.created_at, SeatTermFunding.id).all()


def test_funding_opening_combines_included_and_purchased_seats(db):
    ns = seed(db.session)  # 3 included + 2 purchased = 5
    funding = _funding(db.session, ns.opening)
    assert len(funding) == 1 and funding[0].purpose == "opening" and funding[0].state == "funded"
    assert (funding[0].required_seats, funding[0].funded_seats) == (5, 5)
    rows = {row.seat_source: row for row in db.session.query(SeatFundingAttribution).filter(
        SeatFundingAttribution.id.in_(ns.opening_attributions))}
    assert rows["included"].seats == INCLUDED and rows["included"].entitlement_definition_id == ns.definition
    assert rows["purchased"].seats == 2 and rows["purchased"].entitlement_definition_id is None
    assert all(row.contract_version == 1 for row in rows.values())


@pytest.mark.parametrize("case", ("insufficient", "excess", "no_base_plan", "purchased_only_twice"))
def test_funding_opening_rejects_insufficient_or_mismatched_evidence(db, case):
    ns = seed(db.session, open_commitment=False)
    base = attribute(db.session, ns.subscription, ns.base_line, "included", ANCHOR, ns.renewal)
    extra_line = paid_line(db.session, ns.account, ns.subscription, "seat", ANCHOR, f"ex-{ns.suffix}")
    seats = {"insufficient": 1, "excess": 4, "no_base_plan": 2, "purchased_only_twice": 1}[case]
    purchased = attribute(db.session, ns.subscription, ns.seat_line, "purchased", ANCHOR, ns.renewal, seats=seats)
    ids = {"insufficient": [base, purchased], "excess": [base, purchased], "no_base_plan": [purchased],
           "purchased_only_twice": [purchased, purchased]}[case]
    db.session.commit()
    assert extra_line
    with pytest.raises(SeatFundingError):
        open_seat_commitment(
            db.session, billing_account_id=ns.account, subscription_id=ns.subscription, quantity=5,
            attribution_ids=ids, opened_at=ANCHOR, actor_type="system", actor_id="phase8-test",
            delivery_obligations=DELIVERIES,
        )
    db.session.rollback()
    assert current_seat_commitment(db.session, ns.subscription) is None


def test_funding_included_seats_come_only_from_the_approved_plan_definition(db):
    ns = seed(db.session, included=None, open_commitment=False)
    with pytest.raises(SeatFundingDependencyError):
        attribute(db.session, ns.subscription, ns.base_line, "included", ANCHOR, ns.renewal)
    db.session.rollback()
    ok = seed(db.session, open_commitment=False)
    with pytest.raises(SeatFundingError, match="approved plan definition"):
        attribute(db.session, ok.subscription, ok.base_line, "included", ANCHOR, ok.renewal, seats=10)
    db.session.rollback()


def test_funding_attribution_binds_subscription_kind_and_paid_term(db):
    a = seed(db.session)
    b = seed(db.session)
    paid_at = ANCHOR + timedelta(days=5)
    b_seat = paid_line(db.session, b.account, b.subscription, "seat", paid_at, f"bs-{b.suffix}")
    a_seat = paid_line(db.session, a.account, a.subscription, "seat", paid_at, f"as-{a.suffix}")
    a_base = paid_line(db.session, a.account, a.subscription, "subscription", paid_at, f"ab-{a.suffix}")
    db.session.commit()
    bad = (
        (a.subscription, b_seat, "purchased", paid_at, a.renewal, 1),           # other subscription's payment
        (a.subscription, a_base, "purchased", paid_at, a.renewal, 1),           # base line cannot buy seats
        (a.subscription, a_seat, "included", ANCHOR, a.renewal, None),          # seat line is not the base plan
        (a.subscription, a_seat, "purchased", paid_at, a.renewal + timedelta(days=3), 1),  # not a paid term
        (a.subscription, a_seat, "purchased", paid_at + timedelta(days=1), a.renewal, 1),  # paid before term
        (a.subscription, a_seat, "purchased", a.renewal, add_calendar_months(a.renewal, 2), 1),
    )
    for subscription_id, line, source, starts, ends, seats in bad:
        with pytest.raises(SeatChangeError):
            attribute(db.session, subscription_id, line, source, starts, ends, seats=seats)
        db.session.rollback()
    # The same attribution cannot fund another subscription's increase.
    b_attr = attribute(db.session, b.subscription, b_seat, "purchased", paid_at, b.renewal, seats=1)
    db.session.commit()
    with pytest.raises(SeatFundingError, match="another subscription"):
        increase(db.session, a, "cross", 1, None, paid_at, attribution_ids=[b_attr])
    db.session.rollback()
    # Exact replay of an attribution returns the same record; changed facts conflict.
    again = attribute(db.session, b.subscription, b_seat, "purchased", paid_at, b.renewal, seats=1)
    assert again == b_attr
    with pytest.raises(SeatChangeConflictError):
        attribute(db.session, b.subscription, b_seat, "purchased", paid_at, b.renewal, seats=2)
    db.session.rollback()


def test_funding_increase_needs_purchased_seats_for_the_rest_of_the_term(db):
    ns = seed(db.session)
    paid_at = ANCHOR + timedelta(days=10)
    base = paid_line(db.session, ns.account, ns.subscription, "subscription", ns.renewal, f"nb-{ns.suffix}")
    db.session.commit()
    next_term = renewal_funding(db.session, ns.subscription, ns.renewal, base, INCLUDED)
    db.session.commit()
    with pytest.raises(SeatFundingError):
        increase(db.session, ns, "included-cannot-buy", 3, None, paid_at, attribution_ids=next_term)
    db.session.rollback()
    line = paid_line(db.session, ns.account, ns.subscription, "seat", paid_at, f"inc-{ns.suffix}")
    db.session.commit()
    change, commitment, state = increase(db.session, ns, "two", 2, line, paid_at)
    db.session.commit()
    assert state == "inserted" and commitment.quantity == 7
    funding = _funding(db.session, commitment.id, "increase")[0]
    assert (funding.required_seats, funding.funded_seats, funding.state) == (2, 2, "funded")
    assert _utc(funding.term_starts_at) == paid_at and _utc(funding.term_ends_at) == ns.renewal
    replay = increase(db.session, ns, "two", 2, line, paid_at)
    assert replay[2] == "duplicate" and replay[1].id == commitment.id
    assert db.session.query(SeatFundingUse).filter_by(term_funding_id=funding.id).count() == 1


def test_purchasing_authority_owner_spends_admin_manages(db):
    ns = seed(db.session)
    paid_at = ANCHOR + timedelta(days=4)
    line = paid_line(db.session, ns.account, ns.subscription, "seat", paid_at, f"auth-{ns.suffix}")
    db.session.commit()
    with pytest.raises(SeatChangePermissionError, match="billing owner"):
        increase(db.session, ns, "admin", 1, line, paid_at, user=ns.badmin)
    db.session.rollback()
    change, _commitment, _state = increase(db.session, ns, "owner", 1, line, paid_at, user=ns.payer)
    db.session.commit()
    assert db.session.get(BillingRoleGrant, change.authorizing_role_grant_id).role == "billing_owner"
    assert change.requested_by_user_id == ns.payer
    # The billing admin manages reductions, re-evaluation, and cancellation.
    reduction, _ = reduce(db.session, ns, "admin-reduce", 4, paid_at + timedelta(hours=1), user=ns.badmin)
    db.session.commit()
    cancel_seat_change(
        db.session, seat_change_id=reduction.id, cancelled_at=paid_at + timedelta(hours=2),
        requested_by_user_id=ns.badmin, delivery_obligations=DELIVERIES,
    )
    db.session.commit()
    assert db.session.get(SeatChange, reduction.id).state == "cancelled"


def test_reduction_requires_funding_for_exactly_the_next_commitment(db):
    ns = seed(db.session)
    change, _ = reduce(db.session, ns, "to-four", 4, ANCHOR + timedelta(days=1))
    line = paid_line(db.session, ns.account, ns.subscription, "subscription", ns.renewal, f"rr-{ns.suffix}")
    db.session.commit()
    for seats in (3, 5):  # insufficient, then still paying for the old commitment
        other = paid_line(db.session, ns.account, ns.subscription, "subscription", ns.renewal,
                          f"rr{seats}-{ns.suffix}")
        db.session.commit()
        with pytest.raises(SeatFundingError, match="exactly the reduced commitment"):
            renew(db.session, change.id, other, ns.renewal, seats=seats)
        db.session.rollback()
    _c, commitment, state = renew(db.session, change.id, line, ns.renewal)
    db.session.commit()
    assert state == "inserted" and commitment.quantity == 4
    funding = _funding(db.session, commitment.id, "renewal")[0]
    assert (funding.required_seats, funding.funded_seats, funding.state) == (4, 4, "funded")
    # A reduction can never fall below the plan's included seats.
    other = seed(db.session)
    with pytest.raises(SeatFundingError, match="included seats"):
        reduce(db.session, other, "below-plan", INCLUDED - 1, ANCHOR + timedelta(days=2))
    db.session.rollback()


def test_blocked_renewal_keeps_commitment_and_leaves_term_funding_unresolved(db):
    ns = seed(db.session)  # occupancy 3, commitment 5
    change, _ = reduce(db.session, ns, "to-three", 3, ANCHOR + timedelta(days=1))
    add_member(db.session, ns.org, _user(db.session, ns.suffix, "joiner").id, "creator")
    members = _members(db.session, ns.org)
    line = paid_line(db.session, ns.account, ns.subscription, "subscription", ns.renewal, f"bk-{ns.suffix}")
    db.session.commit()
    # The customer paid for the lower quantity (3); that does not renew 5 seats.
    blocked, commitment, state = renew(db.session, change.id, line, ns.renewal, seats=3)
    db.session.commit()
    assert state == "blocked" and commitment is None and blocked.state == "blocked_occupancy"
    current = current_seat_commitment(db.session, ns.subscription)
    assert current.id == ns.opening and current.quantity == 5
    funding = db.session.get(SeatTermFunding, db.session.get(SeatChangeEvent, blocked.last_event_id).term_funding_id)
    assert (funding.commitment_id, funding.required_seats, funding.funded_seats, funding.state) == (
        ns.opening, 5, 3, "unresolved")
    assert db.session.get(DomainEvent, funding.domain_event_id).event_type == "seat_term_funding_unresolved"
    assert _members(db.session, ns.org) == members  # nobody removed or changed
    # Over-funding is refused; adequate later evidence resolves the term.
    top_line = paid_line(db.session, ns.account, ns.subscription, "seat", ns.renewal + timedelta(days=2), f"tu-{ns.suffix}")
    db.session.commit()
    term_end = _utc(funding.term_ends_at)
    too_much = attribute(db.session, ns.subscription, top_line, "purchased", ns.renewal, term_end, seats=3)
    db.session.commit()
    with pytest.raises(SeatFundingError, match="exceeds"):
        resolve_seat_term_funding(db.session, term_funding_id=funding.id, attribution_ids=[too_much],
                                  recorded_at=ns.renewal + timedelta(days=2), actor_id="adapter",
                                  delivery_obligations=DELIVERIES)
    db.session.rollback()
    top2 = paid_line(db.session, ns.account, ns.subscription, "seat", ns.renewal + timedelta(days=2), f"tu2-{ns.suffix}")
    db.session.commit()
    exact = attribute(db.session, ns.subscription, top2, "purchased", ns.renewal, term_end, seats=2)
    resolved, state = resolve_seat_term_funding(
        db.session, term_funding_id=funding.id, attribution_ids=[exact],
        recorded_at=ns.renewal + timedelta(days=2), actor_id="adapter", delivery_obligations=DELIVERIES,
    )
    db.session.commit()
    assert state == "inserted" and resolved.state == "funded" and resolved.funded_seats == 5
    assert resolved.supersedes_funding_id == funding.id
    replay = resolve_seat_term_funding(
        db.session, term_funding_id=funding.id, attribution_ids=[exact],
        recorded_at=ns.renewal + timedelta(days=2), actor_id="adapter", delivery_obligations=DELIVERIES,
    )
    assert replay == (resolved, "duplicate")
    assert current_seat_commitment(db.session, ns.subscription).quantity == 5


def test_plain_renewal_records_funded_or_unresolved_without_changing_commitment(db):
    ns = seed(db.session)
    full = paid_line(db.session, ns.account, ns.subscription, "subscription", ns.renewal, f"pf-{ns.suffix}")
    db.session.commit()
    ids = renewal_funding(db.session, ns.subscription, ns.renewal, full, 5)
    funding, state = record_seat_renewal_funding(
        db.session, billing_account_id=ns.account, subscription_id=ns.subscription, attribution_ids=ids,
        term_starts_at=ns.renewal, recorded_at=ns.renewal, actor_id="adapter", delivery_obligations=DELIVERIES,
    )
    db.session.commit()
    assert state == "inserted" and funding.state == "funded" and funding.commitment_id == ns.opening
    assert record_seat_renewal_funding(
        db.session, billing_account_id=ns.account, subscription_id=ns.subscription, attribution_ids=ids,
        term_starts_at=ns.renewal, recorded_at=ns.renewal, actor_id="adapter", delivery_obligations=DELIVERIES,
    )[1] == "duplicate"
    short = seed(db.session)
    low = paid_line(db.session, short.account, short.subscription, "subscription", short.renewal, f"pl-{short.suffix}")
    db.session.commit()
    low_ids = renewal_funding(db.session, short.subscription, short.renewal, low, 4)
    unresolved, _ = record_seat_renewal_funding(
        db.session, billing_account_id=short.account, subscription_id=short.subscription,
        attribution_ids=low_ids, term_starts_at=short.renewal, recorded_at=short.renewal,
        actor_id="adapter", delivery_obligations=DELIVERIES,
    )
    db.session.commit()
    assert (unresolved.state, unresolved.funded_seats, unresolved.required_seats) == ("unresolved", 4, 5)
    assert current_seat_commitment(db.session, short.subscription).quantity == 5
    # A reduction due at this renewal must go through the reduction path.
    due = seed(db.session)
    reduce(db.session, due, "due", 4, ANCHOR + timedelta(days=1))
    due_line = paid_line(db.session, due.account, due.subscription, "subscription", due.renewal, f"pd-{due.suffix}")
    db.session.commit()
    due_ids = renewal_funding(db.session, due.subscription, due.renewal, due_line, 4)
    with pytest.raises(SeatChangeConflictError, match="apply it instead"):
        record_seat_renewal_funding(
            db.session, billing_account_id=due.account, subscription_id=due.subscription,
            attribution_ids=due_ids, term_starts_at=due.renewal, recorded_at=due.renewal,
            actor_id="adapter", delivery_obligations=DELIVERIES,
        )
    db.session.rollback()


def test_renewal_requirement_tells_payment_integration_what_to_collect(db):
    ns = seed(db.session)  # occupancy 3
    plain = seat_renewal_requirement(db.session, ns.subscription)
    assert (plain["quantity_due"], plain["included_seats"], plain["purchased_seats_due"]) == (5, 3, 2)
    assert plain["next_term_starts_at"] == ns.renewal
    change, _ = reduce(db.session, ns, "to-three", 3, ANCHOR + timedelta(days=1))
    db.session.commit()
    fits = seat_renewal_requirement(db.session, ns.subscription)
    assert fits["reduction_applies"] and fits["quantity_due"] == 3 and fits["purchased_seats_due"] == 0
    add_member(db.session, ns.org, _user(db.session, ns.suffix, "late").id, "collaborator")
    db.session.commit()
    grown = seat_renewal_requirement(db.session, ns.subscription)
    assert not grown["reduction_applies"] and grown["quantity_due"] == 5
    assert grown["pending_change_id"] == change.id
    missing = seed(db.session, included=None, open_commitment=False)
    with pytest.raises(SeatChangeError):
        seat_renewal_requirement(db.session, missing.subscription)


@pytest.mark.postgres
@PG
def test_postgres_database_enforces_purchasing_authority_and_exact_funding(monkeypatch):
    """With the service checks switched off, the database still refuses."""
    import app.billing_seats as seats_module

    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed(session)
            paid_at = ANCHOR + timedelta(days=4)
            line = paid_line(session, ns.account, ns.subscription, "seat", paid_at, f"db-{ns.suffix}")
            session.commit()
            # 1. Billing admin spending, service authority widened.
            monkeypatch.setattr(seats_module, "SEAT_PURCHASE_BILLING_ROLES", ("billing_owner", "billing_admin"))
            with pytest.raises(sa.exc.DBAPIError):
                increase(session, ns, "admin-bypass", 1, line, paid_at, user=ns.badmin)
                session.commit()
            session.rollback()
            monkeypatch.undo()
            # 2. Funding sum check disabled in the service: commit fails on mismatch.
            real_take = seats_module._take_funding

            def inflated(*args, **kwargs):
                rows, total, ends = real_take(*args, **kwargs)
                return rows, total + 1, ends

            monkeypatch.setattr(seats_module, "_take_funding", inflated)
            with pytest.raises(sa.exc.DBAPIError):
                increase(session, ns, "inflated", 2, line, paid_at, seats=1)
                session.commit()
            session.rollback()
            monkeypatch.undo()
            # 3. Included seats different from the approved definition.
            monkeypatch.setattr(seats_module, "_included_seats", lambda _session, _sub: INCLUDED + 7)
            renewal_line = paid_line(session, ns.account, ns.subscription, "subscription", ns.renewal, f"dbr-{ns.suffix}")
            session.commit()
            with pytest.raises(sa.exc.DBAPIError):
                attribute(session, ns.subscription, renewal_line, "included", ns.renewal,
                          add_calendar_months(ns.renewal, 1))
                session.commit()
            session.rollback()
            monkeypatch.undo()
            # Honest paths still succeed.
            _change, commitment, state = increase(session, ns, "honest", 1, line, paid_at)
            session.commit()
            assert state == "inserted" and commitment.quantity == 6
    finally:
        engine.dispose()


@pytest.mark.postgres
@PG
def test_postgres_blocked_renewal_and_top_up_pass_guards():
    engine = _migrated_engine()
    try:
        with Session(engine, expire_on_commit=False) as session:
            ns = seed(session)
            change, _ = reduce(session, ns, "pg-block", 3, ANCHOR + timedelta(days=1))
            add_member(session, ns.org, _user(session, ns.suffix, "joiner").id, "creator")
            line = paid_line(session, ns.account, ns.subscription, "subscription", ns.renewal, f"pgb-{ns.suffix}")
            session.commit()
            blocked, _c, state = renew(session, change.id, line, ns.renewal, seats=3)
            session.commit()
            assert state == "blocked"
            funding = session.query(SeatTermFunding).filter_by(subscription_id=ns.subscription, purpose="renewal").one()
            assert (funding.state, funding.funded_seats, funding.required_seats) == ("unresolved", 3, 5)
            top = paid_line(session, ns.account, ns.subscription, "seat", ns.renewal + timedelta(days=1), f"pgt-{ns.suffix}")
            session.commit()
            attr = attribute(session, ns.subscription, top, "purchased", ns.renewal, _utc(funding.term_ends_at), seats=2)
            resolved, _ = resolve_seat_term_funding(
                session, term_funding_id=funding.id, attribution_ids=[attr],
                recorded_at=ns.renewal + timedelta(days=1), actor_id="adapter", delivery_obligations=DELIVERIES,
            )
            session.commit()
            assert resolved.state == "funded"
            # A second renewal decision for the same term is refused by the database.
            with pytest.raises(sa.exc.DBAPIError):
                session.execute(sa.text("""
                    INSERT INTO seat_term_fundings (id,billing_account_id,subscription_id,commitment_id,purpose,
                      term_starts_at,term_ends_at,required_seats,funded_seats,state,idempotency_registry_id,domain_event_id)
                    SELECT :id,billing_account_id,subscription_id,commitment_id,'renewal',term_starts_at,term_ends_at,
                      required_seats,required_seats,'funded',idempotency_registry_id,domain_event_id
                    FROM seat_term_fundings WHERE id=:f
                """), {"id": str(uuid.uuid4()), "f": funding.id})
                session.commit()
            session.rollback()
            # A funding decision with valid claim/event evidence but no attached
            # attributions is refused at commit by the reconciliation trigger.
            fid = str(uuid.uuid4())
            later = add_calendar_months(ns.renewal, 1)
            registry, _ = _claim_registry(
                session, "seat_term_funding", f"seat-term-funding:{ns.subscription}:renewal:direct-{fid}", "b" * 64, ANCHOR)
            event, _m, _s = record_domain_event(session, {
                "billing_account_id": ns.account, "event_key": f"seat_term_funded:{fid}",
                "event_type": "seat_term_funded", "aggregate_type": "seat_term_funding", "aggregate_id": fid,
                "occurred_at": later, "reference_ids": [fid],
            }, DELIVERIES)
            with pytest.raises(sa.exc.DBAPIError, match="do not support the recorded funding"):
                session.execute(sa.text("""
                    INSERT INTO seat_term_fundings (id,billing_account_id,subscription_id,commitment_id,purpose,
                      term_starts_at,term_ends_at,required_seats,funded_seats,state,idempotency_registry_id,domain_event_id)
                    VALUES (:id,:account,:sub,:c,'renewal',:start,:end,5,5,'funded',:reg,:evt)
                """), {"id": fid, "account": ns.account, "sub": ns.subscription, "c": ns.opening,
                       "start": later, "end": add_calendar_months(later, 1), "reg": registry.id, "evt": event.id})
                session.commit()
            session.rollback()
            assert current_seat_commitment(session, ns.subscription).quantity == 5
    finally:
        engine.dispose()
