"""D18 row 17: billing family switches, the account boundary and the identity family (I1).

Founder decision 2026-11-26: on isolated staging, row 17 is integrated ahead of
rows 14-16 using synthetic new-model organizations only. Rows 14-16 stay
mandatory before any production cutover. This module is production-compatible
architecture, not staging code; what keeps it inactive is configuration.

**Family switches.** ``BILLING_MODERN_FAMILIES`` lists the command families the
modern model serves, from ``FAMILIES`` in D18 dependency order (identity,
financial/event, credit funding, AI reservation, readers). The list must be a
prefix of that order, and the setting is refused in a production runtime
(``rate_limits.is_production_runtime``). OD-1 Option C: live production charging
is unchanged until the billing integration. Any invalid value enables nothing.
Unset, every family is off.

**Account boundary.** An organization is modern only if it has a
``BillingModelAssignment``. Otherwise it is legacy, and nothing here changes it.
The assignment is one-way: switching a family off never returns an organization
to legacy billing. Its modern commands are refused while legacy writers stay
blocked, so one organization never has two billing authorities. A user is
modern when they own or are a member (any status, as in the Phase 14 candidate
rules) of a modern organization. Modern and legacy users are disjoint:

* only an organization with no legacy billing footprint can be assigned;
* a user cannot join a modern organization while they hold legacy billing
  state or legacy memberships, and a modern user cannot join a legacy one;
* legacy payer, money and entitlement writers (processor customer or
  subscription on a user, legacy payments, credit grants, account entitlements,
  direct plan, status, seat or unlimited edits on the user or organization row)
  refuse modern users and organizations.

``install_legacy_write_guard`` enforces the last two at flush time for every
writer, after a ``FOR KEY SHARE`` lock on the organizations involved, so a write
racing the first assignment of its organization is serialized with it. Phase 14 quarantines modern organizations (``modern_billing_account``),
and the database refuses a modern establishment.

**Known boundary (I4).** Legacy AI metering (``AIOperation``, ``UsageEvent``,
the per-user compatibility counters) is not blocked here. It is written on
ordinary reads and turns, and staging has no AI egress. The AI-reservation
family (I4) must refuse legacy charging for modern organizations at turn
preflight and charge exactly one model.

**Consequence for teams (until rows 14-16).** A normal sign-up owns a lazily
created personal (legacy) organization, so a normally registered user cannot
join a modern organization. Modern organizations take only users with no other
organization (for example the synthetic seed, or SSO-provisioned users). This is
the disjointness guardrail, not a workflow rule.

**Identity family.** ``establish_modern_billing_identity`` is the onboarding
command (ADR-0001: organization, membership, billing account and billing roles
are explicit commands, never created on a read). It creates the active billing
account, the owner's ``billing_owner`` role and the assignment under one
idempotency claim. ``bind_processor_customer`` binds a processor customer to a
modern account once.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import uuid

from sqlalchemy import event, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from .models import (
    AccountEntitlement,
    AIOperation,
    BillingAccount,
    BillingRoleGrant,
    IdempotencyRegistry,
    Organization,
    OrganizationMember,
    Payment,
    PersistentCreditGrant,
    UsageEvent,
    User,
)
from .models_billing_identity import ASSIGNMENT_RULE_VERSION, BillingModelAssignment


FAMILIES = ("identity", "financial_events", "credit_funding", "ai_reservation", "readers")
SETTING = "BILLING_MODERN_FAMILIES"
NAMESPACE = "billing.identity.model_assignment"
PROCESSORS = frozenset({"stripe"})
_CURRENCY = re.compile(r"^[a-z]{3}$")


class BillingCutoverError(Exception):
    """Base class for row-17 cutover refusals."""


class BillingFamilyDisabledError(BillingCutoverError):
    """The command's family is not served by the modern model in this runtime."""


class BillingModelConflictError(BillingCutoverError):
    """A write would mix the legacy and modern billing models."""

    def __init__(self, message, codes=()):
        super().__init__(message)
        self.codes = tuple(codes)


class BillingIdentityError(BillingCutoverError):
    """The identity command's input or state is invalid."""


class BillingIdentityConflictError(BillingIdentityError):
    """The command identity was reused with different facts, or the state already differs."""


class BillingIdentityRetryError(BillingIdentityError):
    """A concurrent command holds the claim; retry the transaction."""


# ---------------------------------------------------------------------------
# Family switches
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CutoverConfig:
    families: frozenset
    errors: tuple

    def enabled(self, family):
        if family not in FAMILIES:
            raise ValueError(f"unknown billing family: {family}")
        return family in self.families


def load_cutover_config(environ=None):
    """Read ``BILLING_MODERN_FAMILIES``. Any error enables nothing (fail closed)."""
    from .rate_limits import is_production_runtime

    environ = os.environ if environ is None else environ
    names = [name.strip() for name in str(environ.get(SETTING) or "").split(",") if name.strip()]
    if not names:
        return CutoverConfig(frozenset(), ())
    errors = []
    if is_production_runtime():
        errors.append(f"{SETTING} is refused in a production runtime (OD-1 Option C)")
    unknown = sorted(set(names) - set(FAMILIES))
    if unknown:
        errors.append(f"{SETTING} names unknown families: {', '.join(unknown)}")
    if len(names) != len(set(names)):
        errors.append(f"{SETTING} repeats a family")
    if not unknown and set(names) != set(FAMILIES[:len(set(names))]):
        errors.append(f"{SETTING} must enable families in D18 order: {', '.join(FAMILIES)}")
    if errors:
        return CutoverConfig(frozenset(), tuple(errors))
    return CutoverConfig(frozenset(names), ())


def cutover_config():
    return load_cutover_config()


def _require_family(family, config):
    config = cutover_config() if config is None else config
    if not config.enabled(family):
        detail = f" ({'; '.join(config.errors)})" if config.errors else ""
        raise BillingFamilyDisabledError(f"the modern billing {family} family is not enabled{detail}")


# ---------------------------------------------------------------------------
# Account boundary
# ---------------------------------------------------------------------------

def assignment_for_organization(session, organization_id):
    if not organization_id:
        return None
    return session.execute(
        select(BillingModelAssignment).where(BillingModelAssignment.organization_id == str(organization_id))
    ).scalar_one_or_none()


def organization_billing_model(session, organization_id):
    """``"modern"`` when the organization has an assignment, else ``"legacy"``. Never changes anything."""
    with session.no_autoflush:
        return "modern" if assignment_for_organization(session, organization_id) is not None else "legacy"


def _organization_ids_for_user(session, user_id):
    """Every organization the user owns or is a member of (any status)."""
    user_id = str(user_id)
    owned = session.execute(select(Organization.id).where(Organization.owner_user_id == user_id)).scalars().all()
    member = session.execute(
        select(OrganizationMember.organization_id).where(OrganizationMember.user_id == user_id)
    ).scalars().all()
    return set(owned) | set(member)


def _modern_ids(session, organization_ids):
    if not organization_ids:
        return set()
    return set(session.execute(
        select(BillingModelAssignment.organization_id)
        .where(BillingModelAssignment.organization_id.in_(sorted(organization_ids)))
    ).scalars().all())


def user_billing_model(session, user_id):
    """``"modern"`` when the user owns or belongs to a modern organization, else ``"legacy"``."""
    if not user_id:
        return "legacy"
    with session.no_autoflush:
        return "modern" if _modern_ids(session, _organization_ids_for_user(session, user_id)) else "legacy"


def _free_allowance():
    from .billing_config import DEFAULT_PLAN_CATALOG
    return int(DEFAULT_PLAN_CATALOG["free"]["monthly_credits"])


def _share_lock(session, organization_ids):
    """Serialize with ``establish`` (``FOR UPDATE`` on the organization): a check and the write it guards see
    either the committed assignment or none, never a race between them (PostgreSQL; a no-op on SQLite).

    ``FOR KEY SHARE``, the lock a foreign-key insert already takes: it conflicts with ``FOR UPDATE`` but not with
    ordinary updates of the organization row, so two legacy transactions that update the same organization never
    deadlock on it."""
    ids = sorted({str(i) for i in organization_ids if i})
    if ids:
        session.execute(select(Organization.id).where(Organization.id.in_(ids)).order_by(Organization.id)
                        .with_for_update(read=True, key_share=True)).all()


def _count(session, model, *conditions):
    return session.execute(select(func.count()).select_from(model).where(*conditions)).scalar_one()


def _user_footprint(session, user_id):
    """Legacy billing state held by one user: processor identity and money, credit and metering rows."""
    codes = []
    user = session.get(User, user_id)
    if user is None:
        return [{"code": "user_missing", "subject": user_id}]
    if user.stripe_customer_id:
        codes.append({"code": "processor_customer", "subject": user_id})
    if getattr(user, "stripe_subscription_id", None):
        codes.append({"code": "processor_subscription", "subject": user_id})
    # Legacy entitlement held on the user row (a plan, a processor status, unlimited or admin-set value, seats).
    if str(user.subscription_plan or "free").strip().lower() != "free":
        codes.append({"code": "legacy_plan", "subject": user_id})
    if user.subscription_status:
        codes.append({"code": "legacy_subscription_status", "subject": user_id})
    if user.unlimited_analysis:
        codes.append({"code": "unlimited_analysis", "subject": user_id})
    if user.credits_remaining is None:
        codes.append({"code": "unlimited_credits", "subject": user_id})
    elif user.credits_remaining > _free_allowance():
        codes.append({"code": "legacy_credit_balance", "subject": user_id})
    if (user.seat_limit or 1) > 1 or (user.max_seats or 1) > 1:
        codes.append({"code": "legacy_seats", "subject": user_id})
    for code, model in (("payments", Payment), ("persistent_credit_grants", PersistentCreditGrant),
                        ("account_entitlements", AccountEntitlement), ("ai_operations", AIOperation),
                        ("usage_events", UsageEvent)):
        if _count(session, model, model.user_id == user_id):
            codes.append({"code": code, "subject": user_id})
    return codes


def legacy_billing_footprint(session, organization_id):
    """Every reason the organization cannot be assigned to the modern model; empty when it can."""
    organization = session.get(Organization, organization_id)
    if organization is None:
        return [{"code": "organization_missing", "subject": organization_id}]
    codes = []
    # A Phase 14 establishment always leaves a billing account, and a Phase 14 payer always carries a processor
    # customer, so both are covered here without this live module naming the inactive backfill. The database
    # guard on the assignment also refuses any organization with a Phase 14 establishment (quarantines included).
    if session.execute(select(BillingAccount.id).where(BillingAccount.organization_id == organization.id)).first():
        codes.append({"code": "billing_account_exists", "subject": organization.id})
    for code, model in (("organization_payments", Payment), ("organization_credit_grants", PersistentCreditGrant),
                        ("organization_entitlements", AccountEntitlement),
                        ("organization_ai_operations", AIOperation), ("organization_usage_events", UsageEvent)):
        if _count(session, model, model.organization_id == organization.id):
            codes.append({"code": code, "subject": organization.id})
    settings = organization.settings if isinstance(organization.settings, dict) else {}
    if "thinking_power" in settings:
        codes.append({"code": "organization_thinking_power", "subject": organization.id})
    if str(organization.plan_key or "free").strip().lower() != "free":
        codes.append({"code": "organization_plan", "subject": organization.id})
    if organization.max_total_paid_seats is not None or organization.seat_policy_overrides:
        codes.append({"code": "organization_seats", "subject": organization.id})
    people = {organization.owner_user_id} if organization.owner_user_id else set()
    people |= set(session.execute(
        select(OrganizationMember.user_id).where(OrganizationMember.organization_id == organization.id)
    ).scalars().all())
    for user_id in sorted(people):
        codes.extend(_user_footprint(session, user_id))
        others = _organization_ids_for_user(session, user_id) - {organization.id}
        for other in sorted(others - _modern_ids(session, others)):
            codes.append({"code": "member_of_legacy_organization", "subject": user_id, "organization": other})
    return codes


def assert_legacy_billing_allowed(session, *, user_id=None, organization_id=None):
    """Refuse a legacy payer or money write for a modern user or organization."""
    with session.no_autoflush:
        _share_lock(session, ({organization_id} if organization_id else set())
                    | (_organization_ids_for_user(session, user_id) if user_id else set()))
        if organization_id and organization_billing_model(session, organization_id) == "modern":
            raise BillingModelConflictError(
                "this organization's billing is managed by the modern billing model", ("modern_organization",))
        if user_id and user_billing_model(session, user_id) == "modern":
            raise BillingModelConflictError(
                "this account's billing is managed by the modern billing model", ("modern_user",))


def assert_membership_compatible(session, *, organization_id, user_id):
    """Refuse a membership that would give one user both billing models."""
    with session.no_autoflush:
        others = _organization_ids_for_user(session, user_id) - {str(organization_id)}
        _share_lock(session, others | {str(organization_id)})
        if organization_billing_model(session, organization_id) == "modern":
            codes = [c["code"] for c in _user_footprint(session, str(user_id))]
            if others - _modern_ids(session, others):
                codes.append("member_of_legacy_organization")
            if codes:
                raise BillingModelConflictError(
                    "a member of a modern billing organization cannot hold legacy billing", codes)
        elif _modern_ids(session, others):
            raise BillingModelConflictError(
                "a member of a modern billing organization cannot join a legacy billing organization",
                ("member_of_modern_organization",))


# ---------------------------------------------------------------------------
# Central legacy write guard (every writer, at flush)
# ---------------------------------------------------------------------------

_MONEY_MODELS = (Payment, PersistentCreditGrant, AccountEntitlement)
_PAYER_FIELDS = ("stripe_customer_id", "stripe_subscription_id")
# Legacy entitlement written straight onto the rows (admin edits, legacy webhooks). Credit counters are not here:
# legacy metering writes them on reads and turns, and that boundary belongs to the AI-reservation family (I4).
_USER_ENTITLEMENT_FIELDS = ("subscription_plan", "subscription_status", "unlimited_analysis", "seat_limit",
                            "max_seats")
_ORGANIZATION_ENTITLEMENT_FIELDS = ("plan_key", "max_total_paid_seats", "seat_policy_overrides")


def _changed(session, obj, names, *, assigned_only=False):
    """True when a governed column receives a value different from the stored one."""
    from sqlalchemy import inspect as sa_inspect

    state = sa_inspect(obj)
    for name in names:
        history = state.attrs[name].history
        if not history.added:
            continue
        if assigned_only and not any(history.added):
            continue
        if history.deleted:
            before = list(history.deleted)
        else:  # the old value was expired (for example after a commit): compare with the stored row
            with session.no_autoflush:
                column = getattr(type(obj), name)
                before = [session.execute(select(column).where(type(obj).id == obj.id)).scalar_one_or_none()]
        if list(history.added) == before:
            continue
        return True
    return False


def _guard_targets(session):
    """``(kind, obj)`` for every pending write the boundary governs, with the organizations each one locks."""
    for obj in session.new:
        if isinstance(obj, OrganizationMember):
            yield "membership", obj, {obj.organization_id}
        elif isinstance(obj, _MONEY_MODELS):
            yield "money", obj, {getattr(obj, "organization_id", None)}
    for obj in session.dirty:
        if isinstance(obj, User) and (_changed(session, obj, _PAYER_FIELDS, assigned_only=True)
                                      or _changed(session, obj, _USER_ENTITLEMENT_FIELDS)):
            yield "user", obj, set()
        elif isinstance(obj, Organization) and _changed(session, obj, _ORGANIZATION_ENTITLEMENT_FIELDS):
            yield "organization", obj, {obj.id}


def _guard_flush(session, flush_context, instances):
    targets = list(_guard_targets(session))
    if not targets:
        return
    with session.no_autoflush:
        locked = set()
        for kind, obj, organizations in targets:
            user_id = obj.id if kind == "user" else getattr(obj, "user_id", None)
            locked |= organizations | (_organization_ids_for_user(session, user_id) if user_id else set())
        _share_lock(session, locked)  # before the shortcut, so a concurrent first assignment cannot slip past it
        if session.execute(select(BillingModelAssignment.id).limit(1)).first() is None:
            return  # no modern organization exists: legacy behavior is untouched
        for kind, obj, _organizations in targets:
            if kind == "membership":
                assert_membership_compatible(session, organization_id=obj.organization_id, user_id=obj.user_id)
            elif kind == "user":
                assert_legacy_billing_allowed(session, user_id=obj.id)
            elif kind == "organization":
                assert_legacy_billing_allowed(session, organization_id=obj.id)
            else:
                assert_legacy_billing_allowed(session, user_id=getattr(obj, "user_id", None),
                                              organization_id=getattr(obj, "organization_id", None))


def install_legacy_write_guard():
    """Register the flush guard for every SQLAlchemy session (idempotent)."""
    if not event.contains(Session, "before_flush", _guard_flush):
        event.listen(Session, "before_flush", _guard_flush)


# ---------------------------------------------------------------------------
# Identity family commands
# ---------------------------------------------------------------------------

def _fingerprint(value):
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _text(name, value, limit):
    value = str(value or "").strip()
    if not value or len(value) > limit:
        raise BillingIdentityError(f"{name} is required (at most {limit} characters)")
    return value


def _database_now(session):
    """Command time from the database: PostgreSQL ``now()`` is the transaction time the guard compares against."""
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        return session.execute(text("SELECT now()")).scalar_one().astimezone(timezone.utc)
    if dialect == "sqlite":
        raw = session.execute(text("SELECT strftime('%Y-%m-%d %H:%M:%f', 'now')")).scalar_one()
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc)
    raise BillingIdentityError(f"unsupported database dialect: {dialect}")


def _claim(session, namespace, key, fingerprint, at):
    """Claim the command identity once (the shared registry); returns ``(registry, claimed)``."""
    values = {"id": str(uuid.uuid4()), "namespace": namespace, "key": key, "request_fingerprint": fingerprint,
              "state": "claimed", "claimed_at": at}
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        statement = postgresql_insert(IdempotencyRegistry).values(**values)
    elif dialect == "sqlite":
        statement = sqlite_insert(IdempotencyRegistry).values(**values)
    else:
        raise BillingIdentityError(f"unsupported database dialect: {dialect}")
    inserted = session.execute(statement.on_conflict_do_nothing(
        index_elements=[IdempotencyRegistry.namespace, IdempotencyRegistry.key]
    ).returning(IdempotencyRegistry.id)).scalar_one_or_none()
    if inserted is not None:
        return session.get(IdempotencyRegistry, inserted), True
    registry = session.execute(select(IdempotencyRegistry).where(
        IdempotencyRegistry.namespace == namespace, IdempotencyRegistry.key == key).with_for_update()
    ).scalar_one_or_none()
    if registry is None:
        raise BillingIdentityRetryError("the identity claim raced under the current snapshot; retry")
    if registry.request_fingerprint != fingerprint:
        raise BillingIdentityConflictError("identity command reused with different facts")
    return registry, False


def _complete(session, registry, at, result_type, result_id):
    session.execute(
        update(IdempotencyRegistry)
        .where(IdempotencyRegistry.id == registry.id, IdempotencyRegistry.state == "claimed")
        .values(state="completed", completed_at=at, result_type=result_type, result_id=result_id,
                last_error_code=None)
        .execution_options(synchronize_session=False)
    )
    session.refresh(registry)
    if (registry.state, registry.result_type, registry.result_id) != ("completed", result_type, result_id):
        raise BillingIdentityConflictError("the identity claim completed with a different result")


def _utc(value):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def establish_modern_billing_identity(session, *, organization_id, actor_user_id, currency, origin_type,
                                      origin_id, config=None):
    """Create a new-model organization's billing account, owner role and assignment.

    Returns ``(assignment, "inserted" | "replayed")``. The caller commits. Refuses
    unless the identity family is enabled, the actor owns the organization, and
    the organization has no legacy billing footprint.
    """
    _require_family("identity", config)
    organization_id = _text("organization_id", organization_id, 36)
    actor_user_id = _text("actor_user_id", actor_user_id, 36)
    origin_type = _text("origin_type", origin_type, 40)
    origin_id = _text("origin_id", origin_id, 255)
    currency = str(currency or "").strip()
    if not _CURRENCY.match(currency):
        raise BillingIdentityError("currency must be a lowercase three-letter ISO code")

    with session.no_autoflush:
        organization = session.execute(
            select(Organization).where(Organization.id == organization_id).with_for_update()
        ).scalar_one_or_none()
        if organization is None:
            raise BillingIdentityError("organization does not exist")
        at = _database_now(session)
        request = {"organization_id": organization_id, "actor_user_id": actor_user_id, "currency": currency,
                   "origin_type": origin_type, "origin_id": origin_id}
        fingerprint = _fingerprint(request)
        registry, claimed = _claim(session, NAMESPACE, f"organization:{organization_id}", fingerprint, at)
        if not claimed:
            existing = assignment_for_organization(session, organization_id)
            if existing is None:
                raise BillingIdentityRetryError("the identity claim exists without its assignment; retry")
            return existing, "replayed"
        if organization.owner_user_id != actor_user_id:
            raise BillingIdentityError("only the organization's owner can establish its billing identity")
        footprint = legacy_billing_footprint(session, organization_id)
        if footprint:
            raise BillingModelConflictError(
                "the organization holds legacy billing state; it reaches the modern model only through the "
                "D18 migration", [c["code"] for c in footprint])

    account = BillingAccount(
        id=str(uuid.uuid4()), organization_id=organization_id, status="active", currency=currency,
        account_anchor_at=_utc(organization.created_at),
    )
    session.add(account)
    session.flush()
    session.add(BillingRoleGrant(
        id=str(uuid.uuid4()), billing_account_id=account.id, user_id=actor_user_id, role="billing_owner",
        starts_at=at, granted_by_user_id=actor_user_id, origin_type="billing_identity_command",
        origin_id=registry.id,
    ))
    members = sorted(set(session.execute(
        select(OrganizationMember.user_id).where(OrganizationMember.organization_id == organization_id)
    ).scalars().all()) | {actor_user_id})
    assignment = BillingModelAssignment(
        id=str(uuid.uuid4()), organization_id=organization_id, billing_account_id=account.id, model="modern",
        rule_version=ASSIGNMENT_RULE_VERSION, assigned_by_user_id=actor_user_id, origin_type=origin_type,
        origin_id=origin_id, footprint_json={"checked_users": members, "codes": []},
        request_fingerprint=fingerprint, idempotency_registry_id=registry.id, assigned_at=at,
    )
    session.add(assignment)
    session.flush()
    _complete(session, registry, at, "billing_model_assignment", assignment.id)
    return assignment, "inserted"


def _billing_authority(session, account_id, user_id, at):
    return session.execute(
        select(BillingRoleGrant.id).where(
            BillingRoleGrant.billing_account_id == account_id, BillingRoleGrant.user_id == user_id,
            BillingRoleGrant.role.in_(("billing_owner", "billing_admin")), BillingRoleGrant.state == "active",
            BillingRoleGrant.starts_at <= at,
            or_(BillingRoleGrant.ends_at.is_(None), BillingRoleGrant.ends_at > at),
        )
    ).first() is not None


def bind_processor_customer(session, *, billing_account_id, processor, processor_customer_id, actor_user_id,
                            config=None):
    """Bind a processor customer to a modern billing account once. Returns ``(account, state)``.

    ``state`` is ``"bound"`` or ``"unchanged"`` (the same customer was already
    bound). A different customer, an unbound legacy account or an actor without
    billing authority is refused. The caller commits.
    """
    _require_family("identity", config)
    billing_account_id = _text("billing_account_id", billing_account_id, 36)
    actor_user_id = _text("actor_user_id", actor_user_id, 36)
    processor_customer_id = _text("processor_customer_id", processor_customer_id, 255)
    if processor not in PROCESSORS:
        raise BillingIdentityError("unsupported processor")
    with session.no_autoflush:
        account = session.execute(
            select(BillingAccount).where(BillingAccount.id == billing_account_id).with_for_update()
        ).scalar_one_or_none()
        if account is None:
            raise BillingIdentityError("billing account does not exist")
        assignment = assignment_for_organization(session, account.organization_id)
        if assignment is None or assignment.billing_account_id != account.id:
            raise BillingModelConflictError("only a modern billing account binds a processor customer here",
                                            ("legacy_billing_account",))
        at = _database_now(session)
        if not _billing_authority(session, account.id, actor_user_id, at):
            raise BillingIdentityError("the actor holds no billing authority on this account")
        if account.processor_customer_id is not None:
            if (account.processor, account.processor_customer_id) == (processor, processor_customer_id):
                return account, "unchanged"
            raise BillingIdentityConflictError("the billing account already has a different processor customer")
        if session.execute(select(User.id).where(User.stripe_customer_id == processor_customer_id)).first():
            raise BillingModelConflictError("the processor customer belongs to a legacy payer",
                                            ("legacy_processor_customer",))
    account.processor = processor
    account.processor_customer_id = processor_customer_id
    session.flush()
    return account, "bound"
