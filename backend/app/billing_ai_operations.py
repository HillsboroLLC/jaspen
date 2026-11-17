"""Inactive Phase 12 AI reservation, capacity, and settlement commands.

Implements lifecycle specification D06 (operation reservation and settlement,
absorbed provider usage evidence), D21 (an operation binds the effective
pricing version), D22 (provider-independent short-term capacity with runaway
bounds), and D23 (credit exhaustion and capacity denial preserve work; resumed
work never repeats a settled step), under the founder-approved delivery-based
billability policy of 2026-11-11 as amended by the founder on 2026-11-16 and
2026-11-17:

* a response is billable only when delivered (shown to the customer or durably
  saved where the customer can access it); quality never matters;
* verified delivered usage stays billable after the original execution
  deadline: the hold is a renewable lease the running worker keeps alive, and
  no timer or cleanup job releases it while the lease is live; a lapsed lease
  releases the hold and nothing is charged after it, but a response that still
  arrives is recorded as delivered (never charged, never re-reserved);
* a delivered response settles the actual billable usage of the provider
  attempt that produced it, converted under the bound pricing version, capped
  by the reservation unless one atomic supplemental reservation succeeds;
  usage above the cap is recorded as Jaspen-absorbed, never dropped;
* undelivered attempts, failed attempts before a fallback delivers, and usage
  that is not provider-reported are never charged; they are recorded as
  Jaspen-absorbed with evidence;
* unknown provider/model economics and missing pricing or capacity policy fail
  closed before any reservation or provider call;
* every active member has an individual fair-use allowance (rolling windows,
  concurrency) inside their organization, whatever its size, while drawing on
  the organization's shared credit balance; organization-level limits may also
  apply but never replace a member's own allowance; fair-use measurements are
  operations and provider tokens, never credits.

The Phase 3 ledger is the only balance authority. No numeric capacity limit,
rate, or conversion is defined here: every number comes from an approved,
effective policy version. Costs are exact decimals computed from the recorded
token quantities and the bound rates, rounded to whole credits once per
settlement. Nothing in the runtime imports this module; the
legacy AI runtime and its credit paths are unchanged until Phase 17.
"""

import contextlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import ROUND_CEILING, ROUND_HALF_EVEN, Decimal, Inexact, InvalidOperation, Rounded, localcontext
import hashlib
import json
import uuid

from sqlalchemy import and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .billing_ledger import (
    CreditLedgerInvariantError,
    append_entry,
    lock_billing_account,
)
from .models import (
    AIOperation,
    BillingAccount,
    CapacityPolicyVersion,
    CreditLedgerEntry,
    CreditLot,
    CreditReservation,
    EntitlementDefinition,
    EntitlementInstance,
    IdempotencyRegistry,
    OrganizationMember,
    PricingPolicyVersion,
    ProviderRateEntry,
)
from .models_billing_phase12 import (
    CALL_COMPONENTS,
    CALL_OUTCOMES,
    CAPACITY_RULES_SCHEMA,
    CONVERSION_KEY,
    COST_USD,
    USAGE_LABELS,
    AIAbsorbedUsage,
    AIBillingOperation,
    AICapacityDecision,
    AIOperationCheckpoint,
    AIProviderCallUsage,
)


AUTHORIZATION_NAMESPACE = "ai_operation_authorization"
RESERVATION_NAMESPACE = "ai_credit_reservation"
LEDGER_NAMESPACE = "ai_credit_ledger"
SYSTEM_ACTOR = ("system", "billing_ai_operations")
ACTIVE_ENTITLEMENT_STATES = ("active", "reducing")
MILLION = Decimal(1_000_000)


class AIBillingError(ValueError):
    """Base error; the caller rolls back its transaction."""


class AIBillingConflictError(AIBillingError):
    """An idempotency identity was reused with different facts."""


class AIBillingRetryError(AIBillingError):
    """A concurrent claim is not visible yet; retry the transaction."""


class AIBillingIsolationError(AIBillingError):
    """The command crossed an organization or billing-account boundary."""


class AIBillingIsolationLevelError(AIBillingError):
    """PostgreSQL commands must run in READ COMMITTED."""


class AIBillingStateError(AIBillingError):
    """The operation is not in a state that allows the command."""


class PricingPolicyRequiredError(AIBillingError):
    """No single effective, complete pricing policy exists (fail closed)."""


class UnpricedModelError(AIBillingError):
    """A provider/model has no exact rate in the bound pricing version."""


class CapacityPolicyRequiredError(AIBillingError):
    """No effective, valid capacity policy covers this account (fail closed)."""


class RunawayLimitError(AIBillingError):
    """A runaway bound was reached; the outcome is typed and resumable."""

    resumable = True

    def __init__(self, message, *, limit):
        super().__init__(message)
        self.limit = limit


class StepAlreadySettledError(AIBillingError):
    """A resumed operation tried to repeat a step that was already settled."""


class ReservationLapsedError(AIBillingStateError):
    """The reservation lease lapsed: nothing more can run, renew, or settle.

    The worker stopped renewing the hold: no further call starts and nothing
    is charged. A response that still arrives is recorded as delivered without
    a charge (``settle_delivered_operation`` after the lapse).
    """


@dataclass(frozen=True)
class AuthorizationResult:
    outcome: str  # authorized | capacity_denied | credit_exhausted
    operation_id: str
    required_credits: int
    available_credits: int | None = None
    reservation_id: str | None = None
    held_credits: int = 0
    reservation_ceiling: int | None = None
    pricing_policy_version_id: str | None = None
    capacity_policy_version_id: str | None = None
    tier_key: str | None = None
    priority: int | None = None
    reason_code: str | None = None
    available_again_at: datetime | None = None
    expires_at: datetime | None = None
    execution_deadline_at: datetime | None = None
    replay: bool = False


@dataclass(frozen=True)
class FinalizationResult:
    operation_id: str
    delivery_status: str | None
    state: str
    charged_credits: int
    absorbed_credits: int
    released_credits: int
    supplemental_credits: int
    replay: bool = False


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _utc(value):
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _fingerprint(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _dialect(session):
    return session.get_bind().dialect.name


def _clock(session):
    """Actual current database time, read after the locks a decision needs."""
    if _dialect(session) == "postgresql":
        return session.execute(text("SELECT clock_timestamp()")).scalar_one().astimezone(timezone.utc)
    raw = session.execute(text("SELECT strftime('%Y-%m-%d %H:%M:%f', 'now')")).scalar_one()
    return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S.%f").replace(tzinfo=timezone.utc)


def _require_read_committed(session):
    """Counts, balances, and checkpoints must see every committed competitor."""
    if _dialect(session) != "postgresql":
        return
    level = session.execute(text("SELECT current_setting('transaction_isolation')")).scalar_one()
    if level != "read committed":
        raise AIBillingIsolationLevelError("AI billing commands must run in a READ COMMITTED transaction")


def _text(value, field, maximum):
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise AIBillingError(f"{field} must be nonempty text of at most {maximum} characters")
    return value


def _count(value, field, *, minimum=0):
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise AIBillingError(f"{field} must be an integer >= {minimum}")
    return value


COST_QUANTUM = Decimal(1).scaleb(-COST_USD[1])


@contextlib.contextmanager
def _exact():
    """Decimal arithmetic that raises instead of rounding (F5: no premature rounding)."""
    with localcontext() as context:
        context.prec = 80
        context.traps[Inexact] = True
        context.traps[Rounded] = True
        yield


def _credits(cost_usd, credits_per_usd):
    """Whole credits under the bound version's ceil_whole_credit rule: one rounding, at the end."""
    with _exact():
        product = cost_usd * credits_per_usd
    return int(product.to_integral_value(rounding=ROUND_CEILING))


def _cost(rate, input_tokens, output_tokens):
    """Exact USD cost of a token quantity under one bound per-1M rate entry."""
    with _exact():
        return (Decimal(input_tokens) * Decimal(rate.input_rate)
                + Decimal(output_tokens) * Decimal(rate.output_rate)) / MILLION


def _call_cost(session, call):
    """A recorded call's exact cost, recomputed from its tokens and its bound rate entry."""
    if call.usage_label == "unknown":
        return None
    rate = session.get(ProviderRateEntry, call.provider_rate_entry_id)
    return _cost(rate, int(call.input_tokens), int(call.output_tokens))


def _total_cost(session, calls):
    with _exact():
        return sum((_call_cost(session, c) for c in calls), Decimal(0))


def _unrecovered_cost(cost_usd, charged_credits, credits_per_usd):
    """The part of an exact provider cost that a capped charge did not recover."""
    with localcontext() as context:
        context.prec = 80
        recovered = Decimal(charged_credits) / credits_per_usd
        remainder = (cost_usd - recovered).quantize(COST_QUANTUM, rounding=ROUND_HALF_EVEN)
    return min(cost_usd, max(Decimal(0), remainder))


def _claim(session, namespace, key, fingerprint, claimed_at):
    values = {
        "id": str(uuid.uuid4()), "namespace": namespace, "key": key,
        "request_fingerprint": fingerprint, "state": "claimed", "claimed_at": claimed_at,
    }
    insert = postgresql_insert if _dialect(session) == "postgresql" else sqlite_insert
    inserted = session.execute(
        insert(IdempotencyRegistry).values(**values).on_conflict_do_nothing(
            index_elements=[IdempotencyRegistry.namespace, IdempotencyRegistry.key],
        ).returning(IdempotencyRegistry.id)
    ).scalar_one_or_none()
    if inserted is not None:
        return session.get(IdempotencyRegistry, inserted), True
    registry = session.execute(
        select(IdempotencyRegistry).where(
            IdempotencyRegistry.namespace == namespace, IdempotencyRegistry.key == key,
        ).with_for_update()
    ).scalar_one_or_none()
    if registry is None:
        raise AIBillingRetryError("idempotency claim raced under the current snapshot; retry")
    if registry.request_fingerprint != fingerprint:
        raise AIBillingConflictError("AI operation identity was reused with different facts")
    return registry, False


def _complete(session, registry, *, completed_at, result_type, result_id):
    session.execute(
        update(IdempotencyRegistry)
        .where(IdempotencyRegistry.id == registry.id, IdempotencyRegistry.state == "claimed")
        .values(state="completed", completed_at=completed_at, result_type=result_type,
                result_id=result_id, last_error_code=None)
        .execution_options(synchronize_session=False)
    )
    session.refresh(registry)
    if registry.result_type != result_type or registry.result_id != result_id:
        raise AIBillingConflictError("idempotency completion does not match the AI billing result")


def _append(session, *, op, lot_id, entry_type, available, held, reservation_id, related_entry_id,
            key, at, reason, evidence):
    entry_id = str(uuid.uuid4())
    registry = IdempotencyRegistry(
        id=str(uuid.uuid4()), namespace=LEDGER_NAMESPACE, key=key,
        request_fingerprint=_fingerprint({"key": key, "lot": lot_id, "available": available, "held": held}),
        state="completed", claimed_at=at, completed_at=at,
        result_type="credit_ledger_entry", result_id=entry_id,
    )
    session.add(registry)
    session.flush()
    entry = CreditLedgerEntry(
        id=entry_id, billing_account_id=op.billing_account_id, lot_id=lot_id, entry_type=entry_type,
        available_delta=available, held_delta=held, reservation_id=reservation_id,
        operation_id=op.operation_id, related_entry_id=related_entry_id,
        idempotency_registry_id=registry.id, effective_at=at, actor_type=SYSTEM_ACTOR[0],
        actor_id=SYSTEM_ACTOR[1], reason_code=reason, evidence_json=evidence,
    )
    try:
        return append_entry(session, entry)
    except CreditLedgerInvariantError as exc:
        raise AIBillingError(str(exc)) from exc


# ---------------------------------------------------------------------------
# Policy binding (D21, D22)
# ---------------------------------------------------------------------------

def _effective_pricing(session, at):
    versions = session.execute(
        select(PricingPolicyVersion).where(
            PricingPolicyVersion.state == "effective", PricingPolicyVersion.effective_at <= at,
        )
    ).scalars().all()
    if len(versions) != 1:
        raise PricingPolicyRequiredError("exactly one effective pricing policy version is required")
    version = versions[0]
    return version, _conversion(version)


def _conversion(version):
    if version.rounding_rule != "ceil_whole_credit":
        raise PricingPolicyRequiredError("the pricing policy's rounding rule is not supported")
    raw = (version.conversion_json or {}).get(CONVERSION_KEY) if isinstance(version.conversion_json, dict) else None
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise PricingPolicyRequiredError(f"the pricing policy must state {CONVERSION_KEY}")
    try:
        value = Decimal(str(raw))
    except InvalidOperation as exc:
        raise PricingPolicyRequiredError(f"{CONVERSION_KEY} is not a decimal") from exc
    if not value.is_finite() or value <= 0:
        raise PricingPolicyRequiredError(f"{CONVERSION_KEY} must be positive")
    return value


def _rate(session, version_id, provider, model):
    rate = session.execute(
        select(ProviderRateEntry).where(
            ProviderRateEntry.pricing_policy_version_id == version_id,
            ProviderRateEntry.provider == provider,
            ProviderRateEntry.model == model,
        )
    ).scalar_one_or_none()
    if rate is None or rate.currency != "usd" or rate.unit_basis != "per_1m_tokens":
        raise UnpricedModelError(f"{provider}/{model} has no exact rate in the bound pricing version")
    return rate


def _positive(rules, key, *, minimum=1):
    value = rules.get(key) if isinstance(rules, dict) else None
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CapacityPolicyRequiredError(f"capacity rule {key} must be an integer >= {minimum}")
    return value


RUNAWAY_RULES = (
    ("max_provider_attempts", 1),
    ("max_tool_iterations", 0),
    ("max_operation_seconds", 1),
    ("reservation_lease_seconds", 1),
    ("max_reserved_credits", 1),
    ("max_call_input_tokens", 1),
    ("max_call_output_tokens", 1),
    ("max_operation_tokens", 1),
)


def _optional_positive(rules, key):
    if key not in rules:
        return None
    return _positive(rules, key)


def _windows(scope_rules, scope, *, required):
    raw = scope_rules.get("windows")
    if raw is None and not required:
        return []
    if not isinstance(raw, list) or (required and not raw):
        raise CapacityPolicyRequiredError(f"{scope} capacity must list at least one usage window")
    windows, keys = [], set()
    for window in raw:
        if not isinstance(window, dict):
            raise CapacityPolicyRequiredError("each usage window must be an object")
        key = window.get("key")
        if not isinstance(key, str) or not key.strip() or len(key) > 40 or key in keys:
            raise CapacityPolicyRequiredError(f"each {scope} usage window needs a unique key")
        keys.add(key)
        normalized = {
            "key": key,
            "window_seconds": _positive(window, "window_seconds"),
            "max_operations": _optional_positive(window, "max_operations"),
            "max_tokens": _optional_positive(window, "max_tokens"),
            "models": None,
        }
        if normalized["max_operations"] is None and normalized["max_tokens"] is None:
            raise CapacityPolicyRequiredError(f"usage window {key} must bound operations or tokens")
        if "models" in window:
            models = window["models"]
            if (not isinstance(models, list) or not models or normalized["max_operations"] is not None
                    or not all(isinstance(m, list) and len(m) == 2 and all(isinstance(v, str) and v for v in m)
                               for m in models)):
                raise CapacityPolicyRequiredError(
                    f"usage window {key} may scope only its token bound to listed provider/model pairs")
            normalized["models"] = sorted({tuple(m) for m in models})
        windows.append(normalized)
    return windows


def _scope(tier, scope, *, required):
    rules = tier.get(scope)
    if rules is None and not required:
        return None
    if not isinstance(rules, dict):
        raise CapacityPolicyRequiredError(f"{scope} capacity rules must be an object")
    normalized = {
        "max_concurrent": _positive(rules, "max_concurrent") if required else _optional_positive(
            rules, "max_concurrent"),
        "windows": _windows(rules, scope, required=required),
    }
    if not required and normalized["max_concurrent"] is None and not normalized["windows"]:
        raise CapacityPolicyRequiredError("organization capacity rules must bound something when present")
    return normalized


def capacity_rules(version):
    """Validate an approved capacity version's rules; anything missing fails closed.

    Every tier states each member's own allowance (concurrency plus one or more
    rolling windows, such as a five-hour and a weekly window) inside their
    organization. Organization-wide aggregate limits are optional and apply in
    addition, never instead. Runaway bounds cover attempts, tool iterations,
    per-call and per-operation tokens (context growth), duration, the
    reservation lease, and reserved exposure. No number has a default.
    """
    rules = version.rules_json
    if not isinstance(rules, dict) or rules.get("schema") != CAPACITY_RULES_SCHEMA:
        raise CapacityPolicyRequiredError(f"capacity rules must use schema {CAPACITY_RULES_SCHEMA}")
    tiers = rules.get("tiers")
    if not isinstance(tiers, dict) or not tiers:
        raise CapacityPolicyRequiredError("capacity rules must define at least one tier")
    normalized = {}
    for key, tier in tiers.items():
        if not isinstance(tier, dict):
            raise CapacityPolicyRequiredError("each capacity tier must be an object")
        normalized[key] = {
            "priority": _positive(tier, "priority", minimum=0),
            "member": _scope(tier, "member", required=True),
            "organization": _scope(tier, "organization", required=False),
        }
    runaway = rules.get("runaway")
    bounds = {name: _positive(runaway, name, minimum=minimum) for name, minimum in RUNAWAY_RULES}
    return {"tiers": normalized, "runaway": bounds}


def _effective_capacity(session, at):
    versions = session.execute(
        select(CapacityPolicyVersion).where(
            CapacityPolicyVersion.state == "effective", CapacityPolicyVersion.effective_at <= at,
        )
    ).scalars().all()
    if len(versions) != 1:
        raise CapacityPolicyRequiredError("exactly one effective capacity policy version is required")
    return versions[0], capacity_rules(versions[0])


def _tier(session, account_id, rules, at):
    keys = session.execute(
        select(EntitlementDefinition.key)
        .join(EntitlementInstance, EntitlementInstance.entitlement_definition_id == EntitlementDefinition.id)
        .where(
            EntitlementInstance.billing_account_id == account_id,
            EntitlementInstance.state.in_(ACTIVE_ENTITLEMENT_STATES),
            EntitlementInstance.starts_at <= at,
        )
        .where((EntitlementInstance.ends_at.is_(None)) | (EntitlementInstance.ends_at > at))
    ).scalars().all()
    covered = [key for key in keys if key in rules["tiers"]]
    if not covered:
        raise CapacityPolicyRequiredError("no active entitlement is covered by the effective capacity policy")
    key = max(covered, key=lambda k: (rules["tiers"][k]["priority"], k))
    return key, rules["tiers"][key]


def _candidates(value):
    if not isinstance(value, (list, tuple)) or not value:
        raise AIBillingError("candidates must list the provider/model pairs the operation may use")
    normalized = []
    for item in value:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise AIBillingError("each candidate is a (provider, model) pair")
        pair = (_text(item[0], "provider", 32), _text(item[1], "model", 255))
        if pair not in normalized:
            normalized.append(pair)
    return normalized


# ---------------------------------------------------------------------------
# Balances and holds (Phase 3 ledger only)
# ---------------------------------------------------------------------------

def _eligible(lot, actor_user_id):
    """Pool lots plus lots attributed to this member; scoped lots fail closed."""
    if lot.eligibility_scope is not None:
        return False
    return lot.member_attribution_id in (None, actor_user_id)


def _lot_rows(session, account_id, at, *, lock):
    query = (
        select(CreditLot)
        .where(
            CreditLot.billing_account_id == account_id,
            CreditLot.available_at <= at,
            (CreditLot.expires_at.is_(None)) | (CreditLot.expires_at > at),
        )
    )
    if lock:
        from .billing_ledger import ordered_lot_balances
        return [(b.lot, b.available) for b in ordered_lot_balances(session, account_id, at)]
    lots = session.execute(query).scalars().all()
    if not lots:
        return []
    sums = dict(session.execute(
        select(CreditLedgerEntry.lot_id, func.coalesce(func.sum(CreditLedgerEntry.available_delta), 0))
        .where(CreditLedgerEntry.lot_id.in_([lot.id for lot in lots]))
        .group_by(CreditLedgerEntry.lot_id)
    ).all())
    return [(lot, int(sums.get(lot.id, 0) or 0)) for lot in lots]


def _spendable(session, account_id, actor_user_id, at, *, lock=True):
    return [
        (lot, available) for lot, available in _lot_rows(session, account_id, at, lock=lock)
        if available > 0 and _eligible(lot, actor_user_id)
    ]


def _hold(session, op, reservation, amount, lots, *, round_number, at):
    remaining = amount
    entries = []
    for lot, available in lots:
        if remaining == 0:
            break
        take = min(available, remaining)
        entries.append(_append(
            session, op=op, lot_id=lot.id, entry_type="reservation", available=-take, held=take,
            reservation_id=reservation.id, related_entry_id=None,
            key=f"reservation:{op.operation_id}:{round_number}:{lot.id}", at=at,
            reason="ai_operation_reservation" if round_number == 1 else "ai_supplemental_reservation",
            evidence={"round": round_number, "pricing_policy_version_id": op.pricing_policy_version_id},
        ))
        remaining -= take
    if remaining:
        raise AIBillingError("credit reservation could not be fully allocated")
    return entries


def _open_holds(session, reservation_id):
    """Each reservation entry's remaining hold after settlements, releases, expirations."""
    entries = session.execute(
        select(CreditLedgerEntry)
        .where(CreditLedgerEntry.reservation_id == reservation_id, CreditLedgerEntry.entry_type == "reservation")
        .order_by(CreditLedgerEntry.created_at, CreditLedgerEntry.id)
    ).scalars().all()
    if not entries:
        return [], 0
    consumed = dict(session.execute(
        select(CreditLedgerEntry.related_entry_id, func.coalesce(func.sum(-CreditLedgerEntry.held_delta), 0))
        .where(
            CreditLedgerEntry.related_entry_id.in_([e.id for e in entries]),
            CreditLedgerEntry.entry_type.in_(("settlement", "release", "expiration", "dispute_reversal")),
        )
        .group_by(CreditLedgerEntry.related_entry_id)
    ).all())
    reserved_total = sum(int(e.held_delta) for e in entries)
    holds = [(e, int(e.held_delta) - int(consumed.get(e.id, 0) or 0)) for e in entries]
    return [(e, amount) for e, amount in holds if amount > 0], reserved_total


def _release_all(session, op, reservation, reason, at):
    holds, _total = _open_holds(session, reservation.id)
    released = 0
    for entry, amount in holds:
        _append(
            session, op=op, lot_id=entry.lot_id, entry_type="release", available=amount, held=-amount,
            reservation_id=reservation.id, related_entry_id=entry.id,
            key=f"release:{entry.id}:{reason}", at=at, reason=f"ai_release_{reason}", evidence={"reason": reason},
        )
        released += amount
    return released


# ---------------------------------------------------------------------------
# Capacity evaluation (D22): audit evidence, never a ledger entry
# ---------------------------------------------------------------------------

def _rolled_out(stamped, maximum, window_seconds):
    """When enough of the oldest (time, amount) usage leaves the window to fall below the bound."""
    total = sum(amount for _at, amount in stamped)
    if total < maximum:
        return None
    for at, amount in stamped:
        total -= amount
        if total < maximum:
            return at + timedelta(seconds=window_seconds)
    return None  # unreachable: total reaches zero


def _window(session, *, op, member, window, candidates, at):
    """One rolling usage window (D22): authorized operations and/or delivered, verified provider tokens."""
    since = at - timedelta(seconds=window["window_seconds"])
    evidence, waits = {}, []
    if window["max_operations"] is not None:
        filters = [AICapacityDecision.organization_id == op.organization_id]
        if member:
            filters.append(AICapacityDecision.member_user_id == op.actor_user_id)
        times = [_utc(t) for t in session.execute(
            select(AICapacityDecision.decided_at)
            .where(*filters, AICapacityDecision.outcome == "authorized", AICapacityDecision.decided_at > since)
            .order_by(AICapacityDecision.decided_at)
        ).scalars()]
        evidence["operations"] = len(times)
        waits.append(_rolled_out([(t, 1) for t in times], window["max_operations"], window["window_seconds"]))
    models = window["models"]
    if window["max_tokens"] is not None and (models is None or set(candidates) & set(models)):
        filters = [AIBillingOperation.organization_id == op.organization_id]
        if member:
            filters.append(AIBillingOperation.actor_user_id == op.actor_user_id)
        if models is not None:
            filters.append(or_(*(and_(AIProviderCallUsage.provider == p, AIProviderCallUsage.model == m)
                                 for p, m in models)))
        # The allowance is consumed by verified usage of delivered responses: the
        # delivering attempt's provider-reported calls, counted once from their
        # evidence rows (retries and replayed settlements add nothing). Failed and
        # undelivered work is bounded by the operation windows, concurrency and
        # runaway bounds instead (founder decision 2026-11-17).
        stamped = [(_utc(t), int(i) + int(o)) for t, i, o in session.execute(
            select(AIProviderCallUsage.recorded_at, AIProviderCallUsage.input_tokens,
                   AIProviderCallUsage.output_tokens)
            .join(AIBillingOperation, AIBillingOperation.operation_id == AIProviderCallUsage.operation_id)
            .where(*filters, AIBillingOperation.delivery_status == "delivered",
                   AIProviderCallUsage.attempt_number == AIBillingOperation.delivered_attempt_number,
                   AIProviderCallUsage.usage_label == "reported", AIProviderCallUsage.recorded_at > since)
            .order_by(AIProviderCallUsage.recorded_at)
        ).all()]
        evidence["tokens"] = sum(amount for _t, amount in stamped)
        waits.append(_rolled_out(stamped, window["max_tokens"], window["window_seconds"]))
    waits = [w for w in waits if w is not None]
    return evidence, (max(waits) if waits else None)


def _concurrent(session, filters, maximum, at, exclude):
    """Operations whose reservation lease is live; a lapsed lease no longer occupies a slot."""
    running = session.execute(
        select(AIBillingOperation.execution_deadline_at, AIBillingOperation.lease_seconds).where(
            *filters, AIBillingOperation.state == "authorized",
            AIBillingOperation.expires_at > at, AIBillingOperation.operation_id != exclude,
        )
    ).all()
    if len(running) < maximum:
        return len(running), None
    # Safe upper bound: a lease can never be renewed past its deadline plus one lease period.
    limits = sorted(_utc(deadline) + timedelta(seconds=int(lease)) for deadline, lease in running)
    return len(running), limits[len(limits) - maximum]


def _concurrency(session, filters, maximum, at, exclude):
    count, available_again_at = _concurrent(session, filters, maximum, at, exclude)
    return {"running": count}, available_again_at


def _evaluate_capacity(session, *, op, account, tier_rules, candidates, unavailable_providers, at):
    """Fair use (D22; founder decision 2026-11-16).

    Every member is held to their own allowance inside this organization,
    whatever the organization's size; organization limits, when the policy has
    them, are checked as well. Measurements are operations and provider tokens,
    never credits, so a purchased balance never buys past an allowance.
    """
    evidence = {"tier_priority": tier_rules["priority"]}
    if account.status != "active":
        return "account_restricted", None, evidence
    org_rules, member_rules = tier_rules["organization"], tier_rules["member"]
    org_running = (AIBillingOperation.organization_id == op.organization_id,)
    member_running = org_running + (AIBillingOperation.actor_user_id == op.actor_user_id,)
    checks = []
    for scope, rules in (("organization", org_rules), ("member", member_rules)):
        for window in (rules or {}).get("windows", []):
            checks.append((f"{scope}_window", window["key"], lambda w=window, m=(scope == "member"): _window(
                session, op=op, member=m, window=w, candidates=candidates, at=at)))
    for scope, rules, filters in (("organization", org_rules, org_running),
                                  ("member", member_rules, member_running)):
        if rules and rules["max_concurrent"] is not None:
            checks.append((f"{scope}_concurrency", None, lambda r=rules, f=filters: _concurrency(
                session, f, r["max_concurrent"], at, op.operation_id)))
    for reason, window_key, check in checks:
        found, available_again_at = check()
        evidence[f"{reason}:{window_key}" if window_key else reason] = found
        if available_again_at is not None:
            if window_key:
                evidence["denied_window"] = window_key
            return reason, available_again_at, evidence
    pressure = {}
    for provider, when in (unavailable_providers or {}).items():
        when = _utc(when)
        if when is None or when <= at:
            continue
        pressure[provider] = when
    providers = {provider for provider, _model in candidates}
    if providers and providers <= set(pressure):
        evidence["provider_pressure"] = sorted(providers)
        return "provider_pressure", min(pressure[p] for p in providers), evidence
    return None, None, evidence


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _authorization_result(op, *, replay, available=None):
    denied = op.state == "capacity_denied"
    return AuthorizationResult(
        outcome="capacity_denied" if denied else "authorized",
        operation_id=op.operation_id, required_credits=int(op.initial_hold_credits),
        available_credits=available, reservation_id=getattr(op, "_reservation_id", None),
        held_credits=0 if denied else int(op.initial_hold_credits),
        reservation_ceiling=int(op.reservation_ceiling_credits),
        pricing_policy_version_id=op.pricing_policy_version_id,
        capacity_policy_version_id=op.capacity_policy_version_id, tier_key=op.tier_key,
        priority=int(op.priority),
        reason_code=(op.finalization_evidence_json or {}).get("capacity_reason") if denied else None,
        available_again_at=_utc(op.available_again_at), expires_at=_utc(op.expires_at),
        execution_deadline_at=_utc(op.execution_deadline_at), replay=replay,
    )


def _reservation(session, operation_id, *, lock=False):
    query = select(CreditReservation).where(CreditReservation.operation_id == operation_id)
    if lock:
        query = query.with_for_update()
    return session.execute(query).scalar_one_or_none()


def _with_reservation(session, op):
    reservation = _reservation(session, op.operation_id)
    op._reservation_id = reservation.id if reservation else None
    return op


def _account_for(session, organization_id):
    account = session.execute(
        select(BillingAccount).where(BillingAccount.organization_id == organization_id)
    ).scalar_one_or_none()
    if account is None:
        raise AIBillingIsolationError("the operation's organization has no billing account")
    return account


def _active_member(session, organization_id, user_id):
    member = session.execute(
        select(OrganizationMember).where(
            OrganizationMember.organization_id == organization_id,
            OrganizationMember.user_id == user_id,
            OrganizationMember.status == "active",
        )
    ).scalar_one_or_none()
    if member is None:
        raise AIBillingIsolationError("the actor is not an active member of the operation's organization")


def _completed_steps(session, root_operation_id):
    return set(session.execute(
        select(AIOperationCheckpoint.step_key).where(AIOperationCheckpoint.root_operation_id == root_operation_id)
    ).scalars())


def _request_bound(runaway, max_input_tokens, max_output_tokens, required):
    """The first runaway bound a requested operation would exceed (D22), or None."""
    if max_input_tokens > runaway["max_call_input_tokens"]:
        return "max_call_input_tokens"
    if max_output_tokens > runaway["max_call_output_tokens"]:
        return "max_call_output_tokens"
    if max_input_tokens + max_output_tokens > runaway["max_operation_tokens"]:
        return "max_operation_tokens"
    if required > runaway["max_reserved_credits"]:
        return "max_reserved_credits"
    return None


def preflight_ai_operation(session, *, operation_id, actor_user_id, candidates, max_input_tokens,
                           max_output_tokens):
    """Pure availability query (D06): no lock, no claim, no row is written."""
    op = session.get(AIOperation, operation_id)
    if op is None or op.organization_id is None:
        raise AIBillingIsolationError("the operation has no durable organization context")
    if op.user_id != actor_user_id:
        raise AIBillingIsolationError("the operation belongs to another member")
    account = _account_for(session, op.organization_id)
    _active_member(session, op.organization_id, actor_user_id)
    at = _clock(session)
    pricing, per_usd = _effective_pricing(session, at)
    pairs = _candidates(candidates)
    required = max(1, max(
        _credits(_cost(_rate(session, pricing.id, p, m), _count(max_input_tokens, "max_input_tokens"),
                       _count(max_output_tokens, "max_output_tokens")), per_usd)
        for p, m in pairs
    ))
    capacity, rules = _effective_capacity(session, at)
    tier_key, _tier_rules = _tier(session, account.id, rules, at)
    available = sum(a for _lot, a in _spendable(session, account.id, actor_user_id, at, lock=False))
    exceeded = _request_bound(rules["runaway"], max_input_tokens, max_output_tokens, required)
    return {
        "pricing_policy_version_id": pricing.id, "capacity_policy_version_id": capacity.id,
        "tier_key": tier_key, "required_credits": required, "available_credits": available,
        "runaway_limit": exceeded, "sufficient": available >= required and exceeded is None,
    }


def authorize_ai_operation(session, *, operation_id, actor_user_id, step_key, candidates, max_input_tokens,
                           max_output_tokens, root_operation_id=None, resumed_from_operation_id=None,
                           unavailable_providers=None):
    """Bind pricing and capacity, reserve credits, then authorize capacity (D06, D21, D22).

    The hold is a reservation lease: the running worker renews it with
    ``renew_ai_operation_reservation`` and no provider call may start after
    ``execution_deadline_at``. Credit exhaustion returns ``credit_exhausted``
    and writes nothing. A
    capacity denial releases the new reservation in the same transaction,
    records the decision, and returns ``available_again_at``. Replay with the
    same facts returns the recorded result and writes nothing.
    """
    _require_read_committed(session)
    step_key = _text(step_key, "step_key", 160)
    pairs = _candidates(candidates)
    max_input_tokens = _count(max_input_tokens, "max_input_tokens")
    max_output_tokens = _count(max_output_tokens, "max_output_tokens")
    if (root_operation_id is None) != (resumed_from_operation_id is None):
        raise AIBillingError("a resumed operation names both its root and the operation it resumes")
    fingerprint = _fingerprint({
        "operation": operation_id, "actor": actor_user_id, "step": step_key,
        "candidates": [list(p) for p in pairs], "max_input_tokens": max_input_tokens,
        "max_output_tokens": max_output_tokens, "root": root_operation_id,
        "resumed_from": resumed_from_operation_id,
    })

    op_row = session.get(AIOperation, operation_id)
    if op_row is None or op_row.organization_id is None:
        raise AIBillingIsolationError("the operation has no durable organization context")
    if op_row.user_id != actor_user_id:
        raise AIBillingIsolationError("the operation belongs to another member")
    account = _account_for(session, op_row.organization_id)
    lock_billing_account(session, account.id)
    session.refresh(account)
    existing = session.get(AIBillingOperation, operation_id)
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise AIBillingConflictError("AI operation identity was reused with different facts")
        return _authorization_result(_with_reservation(session, existing), replay=True)
    if op_row.billing_account_id not in (None, account.id):
        raise AIBillingIsolationError("the operation is linked to another billing account")
    _active_member(session, op_row.organization_id, actor_user_id)

    if root_operation_id is not None:
        root = session.get(AIBillingOperation, root_operation_id)
        previous = session.get(AIBillingOperation, resumed_from_operation_id)
        if root is None or previous is None:
            raise AIBillingStateError("the resumed operation lineage does not exist")
        if root.root_operation_id is not None or (previous.root_operation_id or previous.operation_id) != root.operation_id:
            raise AIBillingStateError("the resumed operation does not belong to this root")
        if root.billing_account_id != account.id or previous.billing_account_id != account.id:
            raise AIBillingIsolationError("a resumed operation stays within one billing account")
        if previous.state == "authorized":
            raise AIBillingStateError("the interrupted operation is still running; finish or expire it first")
        if step_key in _completed_steps(session, root.operation_id):
            raise StepAlreadySettledError("this step was already completed and settled; it is never repeated")

    at = _clock(session)
    pricing, per_usd = _effective_pricing(session, at)
    rates = {pair: _rate(session, pricing.id, *pair) for pair in pairs}
    capacity, rules = _effective_capacity(session, at)
    tier_key, tier_rules = _tier(session, account.id, rules, at)
    runaway = rules["runaway"]
    required = max(1, max(_credits(_cost(rate, max_input_tokens, max_output_tokens), per_usd)
                          for rate in rates.values()))
    exceeded = _request_bound(runaway, max_input_tokens, max_output_tokens, required)
    if exceeded is not None:
        raise RunawayLimitError(f"the requested operation exceeds the policy's {exceeded} bound", limit=exceeded)
    lots = _spendable(session, account.id, actor_user_id, at)
    available = sum(a for _lot, a in lots)
    if available < required:
        return AuthorizationResult(
            outcome="credit_exhausted", operation_id=operation_id, required_credits=required,
            available_credits=available, pricing_policy_version_id=pricing.id,
            capacity_policy_version_id=capacity.id, tier_key=tier_key, priority=tier_rules["priority"],
        )

    registry, _new = _claim(session, AUTHORIZATION_NAMESPACE, f"ai-operation:{operation_id}", fingerprint, at)
    execution_deadline_at = at + timedelta(seconds=runaway["max_operation_seconds"])
    lease = runaway["reservation_lease_seconds"]
    expires_at = at + timedelta(seconds=lease)
    op = AIBillingOperation(
        operation_id=operation_id, billing_account_id=account.id, organization_id=op_row.organization_id,
        actor_user_id=actor_user_id, pricing_policy_version_id=pricing.id,
        capacity_policy_version_id=capacity.id, root_operation_id=root_operation_id,
        resumed_from_operation_id=resumed_from_operation_id, step_key=step_key,
        idempotency_registry_id=registry.id, request_fingerprint=fingerprint,
        candidates_json=[list(p) for p in pairs], tier_key=tier_key, priority=tier_rules["priority"],
        max_provider_attempts=runaway["max_provider_attempts"],
        max_tool_iterations=runaway["max_tool_iterations"],
        max_call_input_tokens=runaway["max_call_input_tokens"],
        max_call_output_tokens=runaway["max_call_output_tokens"],
        max_operation_tokens=runaway["max_operation_tokens"], lease_seconds=lease,
        initial_hold_credits=required, reservation_ceiling_credits=runaway["max_reserved_credits"],
        state="authorized", authorized_at=at, execution_deadline_at=execution_deadline_at, expires_at=expires_at,
    )
    session.add(op)
    session.flush()
    for column, value in (("billing_account_id", account.id), ("pricing_policy_version_id", pricing.id),
                          ("capacity_policy_version_id", capacity.id)):
        if getattr(op_row, column) not in (None, value):
            raise AIBillingConflictError(f"the operation is already bound to another {column}")
        setattr(op_row, column, value)
    session.flush()

    reservation_registry, _new = _claim(
        session, RESERVATION_NAMESPACE, f"reservation:{operation_id}", fingerprint, at,
    )
    reservation = CreditReservation(
        id=str(uuid.uuid4()), billing_account_id=account.id, operation_id=operation_id,
        pricing_policy_version_id=pricing.id, capacity_policy_version_id=capacity.id,
        idempotency_registry_id=reservation_registry.id, requested_amount=runaway["max_reserved_credits"],
        authorized_amount=runaway["max_reserved_credits"], state="reserved", request_fingerprint=fingerprint,
        created_at=at, expires_at=expires_at,
    )
    session.add(reservation)
    session.flush()
    _hold(session, op, reservation, required, lots, round_number=1, at=at)
    _complete(session, reservation_registry, completed_at=at, result_type="credit_reservation",
              result_id=reservation.id)

    decided_at = _clock(session)
    reason, available_again_at, evidence = _evaluate_capacity(
        session, op=op, account=account, tier_rules=tier_rules, candidates=pairs,
        unavailable_providers=unavailable_providers, at=decided_at,
    )
    session.add(AICapacityDecision(
        operation_id=operation_id, capacity_policy_version_id=capacity.id,
        organization_id=op.organization_id, member_user_id=actor_user_id,
        window_key=f"organization:{op.organization_id}|member:{actor_user_id}", tier_key=tier_key,
        outcome="denied" if reason else "authorized", reason_code=reason,
        available_again_at=available_again_at if reason else None, decided_at=decided_at,
        evidence_json=evidence,
    ))
    session.flush()
    if reason:
        _release_all(session, op, reservation, "capacity_denied", decided_at)
        reservation.state, reservation.finalized_at = "released", decided_at
        op.state, op.finalized_at = "capacity_denied", decided_at
        op.available_again_at = available_again_at
        op.finalization_evidence_json = {"capacity_reason": reason}
        session.flush()
    _complete(session, registry, completed_at=decided_at, result_type="ai_billing_operation",
              result_id=operation_id)
    op._reservation_id = reservation.id
    return _authorization_result(op, replay=False, available=available)


def _lease_limit(op):
    """A lease is never renewed past the execution deadline plus one lease period."""
    return _utc(op.execution_deadline_at) + timedelta(seconds=int(op.lease_seconds))


def _recorded_tokens(session, operation_id):
    return int(session.execute(
        select(func.coalesce(func.sum(AIProviderCallUsage.input_tokens + AIProviderCallUsage.output_tokens), 0))
        .where(AIProviderCallUsage.operation_id == operation_id, AIProviderCallUsage.usage_label != "unknown")
    ).scalar_one() or 0)


def check_provider_call(session, *, operation_id, attempt_number, call_index, provider, model, max_input_tokens,
                        max_output_tokens):
    """Pure pre-call runaway check (D22): the runtime runs it before every provider request.

    Refuses, with a typed and resumable outcome, a call that would start after
    the execution deadline or exceed the attempt, tool-iteration, per-call
    token, or per-operation token (context growth) bound. A lapsed lease
    refuses every new call. Nothing is written.
    """
    op = session.get(AIBillingOperation, operation_id)
    if op is None:
        raise AIBillingStateError("the operation was not authorized")
    if op.state != "authorized":
        raise AIBillingStateError("the operation is closed; no further provider call can start")
    attempt_number = _count(attempt_number, "attempt_number", minimum=1)
    call_index = _count(call_index, "call_index")
    max_input_tokens = _count(max_input_tokens, "max_input_tokens")
    max_output_tokens = _count(max_output_tokens, "max_output_tokens")
    at = _clock(session)
    if at >= _utc(op.expires_at):
        raise ReservationLapsedError("the reservation lease lapsed; no further provider call can start")
    if at >= _utc(op.execution_deadline_at):
        raise RunawayLimitError("operation duration bound reached", limit="max_operation_seconds")
    if [provider, model] not in op.candidates_json:
        raise UnpricedModelError(f"{provider}/{model} was not authorized for this operation")
    if attempt_number > op.max_provider_attempts:
        raise RunawayLimitError("provider attempt bound reached", limit="max_provider_attempts")
    if call_index > op.max_tool_iterations:
        raise RunawayLimitError("tool iteration bound reached", limit="max_tool_iterations")
    if max_input_tokens > op.max_call_input_tokens:
        raise RunawayLimitError("per-call input (context) bound reached", limit="max_call_input_tokens")
    if max_output_tokens > op.max_call_output_tokens:
        raise RunawayLimitError("per-call output bound reached", limit="max_call_output_tokens")
    used = _recorded_tokens(session, operation_id)
    if used + max_input_tokens + max_output_tokens > op.max_operation_tokens:
        raise RunawayLimitError("operation token (context growth) bound reached", limit="max_operation_tokens")
    if session.execute(select(AIProviderCallUsage.id).where(
            AIProviderCallUsage.operation_id == operation_id,
            AIProviderCallUsage.attempt_number == attempt_number,
            AIProviderCallUsage.call_index == call_index)).first() is not None:
        raise AIBillingConflictError("this provider call identity was already recorded")
    return {
        "execution_deadline_at": _utc(op.execution_deadline_at), "lease_expires_at": _utc(op.expires_at),
        "remaining_operation_tokens": int(op.max_operation_tokens) - used,
    }


def renew_ai_operation_reservation(session, *, operation_id):
    """Heartbeat: keep a running operation's hold while its worker is alive.

    Extends the lease to one lease period from now, never past the execution
    deadline plus one lease period, and never shortens it. A lapsed lease cannot
    be revived: the operation was abandoned and may only end undelivered. No
    balance changes, so the billing account is not locked.
    """
    _require_read_committed(session)
    op = session.execute(
        select(AIBillingOperation).where(AIBillingOperation.operation_id == operation_id).with_for_update()
    ).scalar_one_or_none()
    if op is None:
        raise AIBillingStateError("the operation was not authorized")
    session.refresh(op)
    if op.state != "authorized":
        raise AIBillingStateError("the operation is closed; its reservation cannot be renewed")
    at = _clock(session)
    if at >= _utc(op.expires_at):
        raise ReservationLapsedError("the reservation lease lapsed; it cannot be renewed")
    renewed = min(at + timedelta(seconds=int(op.lease_seconds)), _lease_limit(op))
    if renewed > _utc(op.expires_at):
        reservation = _reservation(session, operation_id, lock=True)
        op.expires_at = renewed
        reservation.expires_at = renewed
        session.flush()
    return _utc(op.expires_at)


def record_provider_call(session, *, operation_id, attempt_number, call_index, component, provider, model,
                         outcome, usage_label, input_tokens=None, output_tokens=None, requested_at,
                         finished_at=None, error_category=None, provider_request_id=None,
                         provider_reported_cost_usd=None):
    """Record one provider call of the operation (retry, fallback, tool, context: one operation).

    Evidence of provider usage is recorded even after the lease lapsed, so
    Jaspen's unrecovered provider cost stays accurate; on an expired operation
    the late call is absorbed at once.
    """
    _require_read_committed(session)
    if component not in CALL_COMPONENTS or outcome not in CALL_OUTCOMES or usage_label not in USAGE_LABELS:
        raise AIBillingError("unsupported component, outcome, or usage label")
    attempt_number = _count(attempt_number, "attempt_number", minimum=1)
    call_index = _count(call_index, "call_index")
    if usage_label == "unknown":
        if input_tokens is not None or output_tokens is not None:
            raise AIBillingError("unknown usage carries no token counts")
    else:
        input_tokens = _count(input_tokens, "input_tokens")
        output_tokens = _count(output_tokens, "output_tokens")
    if outcome != "succeeded" and not error_category:
        raise AIBillingError("a failed call needs its error category")
    reported_cost = None if provider_reported_cost_usd is None else Decimal(str(provider_reported_cost_usd))
    facts = {
        "attempt": attempt_number, "call": call_index, "component": component, "provider": provider,
        "model": model, "outcome": outcome, "label": usage_label, "in": input_tokens, "out": output_tokens,
        "requested_at": _utc(requested_at).isoformat(),
        "finished_at": _utc(finished_at).isoformat() if finished_at else None,
        "error": error_category, "request_id": provider_request_id,
        "reported_cost": str(reported_cost) if reported_cost is not None else None,
    }
    fingerprint = _fingerprint(facts)
    # Account then operation: the settlement lock order, since late evidence can change absorbed totals.
    op = _locked_operation(session, operation_id)
    existing = session.execute(
        select(AIProviderCallUsage).where(
            AIProviderCallUsage.operation_id == operation_id,
            AIProviderCallUsage.attempt_number == attempt_number,
            AIProviderCallUsage.call_index == call_index,
        )
    ).scalar_one_or_none()
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise AIBillingConflictError("provider call identity was reused with different usage")
        return existing, "duplicate"
    if op.state not in ("authorized", "expired"):
        raise AIBillingStateError("the operation is closed; no further provider call can be recorded")
    if [provider, model] not in op.candidates_json:
        raise UnpricedModelError(f"{provider}/{model} was not authorized for this operation")
    if attempt_number > op.max_provider_attempts:
        raise RunawayLimitError("provider attempt bound reached", limit="max_provider_attempts")
    if call_index > op.max_tool_iterations:
        raise RunawayLimitError("tool iteration bound reached", limit="max_tool_iterations")
    rate = _rate(session, op.pricing_policy_version_id, provider, model)
    at = _clock(session)
    usage = AIProviderCallUsage(
        operation_id=operation_id, attempt_number=attempt_number, call_index=call_index, component=component,
        provider=provider, model=model, provider_rate_entry_id=rate.id, outcome=outcome,
        error_category=error_category, usage_label=usage_label, input_tokens=input_tokens,
        output_tokens=output_tokens, provider_reported_cost_usd=reported_cost,
        computed_cost_usd=None if usage_label == "unknown" else _cost(rate, input_tokens, output_tokens),
        provider_request_id=provider_request_id, requested_at=requested_at, finished_at=finished_at,
        recorded_at=at, request_fingerprint=fingerprint,
    )
    session.add(usage)
    session.flush()
    if op.state == "expired":
        late = _absorb_attempts(session, op, [usage], reason="reservation_expired", delivery_status="unsettled",
                                per_usd=_bound_conversion(session, op), at=at)
        _finalize(session, op, absorbed_credits=int(op.absorbed_credits or 0) + late)
    return usage, "inserted"


def _calls(session, operation_id):
    return session.execute(
        select(AIProviderCallUsage).where(AIProviderCallUsage.operation_id == operation_id)
        .order_by(AIProviderCallUsage.attempt_number, AIProviderCallUsage.call_index)
    ).scalars().all()


def _absorbed_call_ids(session, operation_id):
    ids = set()
    for row in session.execute(
        select(AIAbsorbedUsage.provider_call_ids_json).where(AIAbsorbedUsage.operation_id == operation_id)
    ).scalars():
        ids.update(row or [])
    return ids


def _label(calls):
    labels = {c.usage_label for c in calls}
    return "unknown" if "unknown" in labels else "estimated" if "estimated" in labels else "reported"


def _absorb(session, op, calls, *, reason, delivery_status, per_usd, at, fallback_attempted=False,
            fallback_outcome=None, charged_credits=0):
    """One immutable evidence row for a set of provider calls Jaspen absorbs.

    ``computed_cost_usd`` is the calls' exact provider cost under the bound
    rates. When a capped charge recovered part of it (``charged_credits``), the
    absorbed credits and the absorbed cost are both only the unrecovered part.
    """
    known = [c for c in calls if c.usage_label != "unknown"]
    cost = _total_cost(session, known) if known else None
    if cost is None:
        absorbed_cost = credits = None
    elif charged_credits:
        credits = _credits(cost, per_usd) - charged_credits
        absorbed_cost = _unrecovered_cost(cost, charged_credits, per_usd)
    else:
        credits, absorbed_cost = _credits(cost, per_usd), cost
    failed = [c for c in calls if c.outcome != "succeeded"]
    row = AIAbsorbedUsage(
        operation_id=op.operation_id, billing_account_id=op.billing_account_id,
        attempt_number=calls[0].attempt_number if len({c.attempt_number for c in calls}) == 1 else None,
        provider=calls[0].provider if len({c.provider for c in calls}) == 1 else None,
        model=calls[0].model if len({c.model for c in calls}) == 1 else None,
        provider_call_ids_json=[c.id for c in calls],
        provider_request_ids_json=[c.provider_request_id for c in calls if c.provider_request_id],
        usage_label=_label(calls),
        input_tokens=sum(int(c.input_tokens) for c in known) if known else None,
        output_tokens=sum(int(c.output_tokens) for c in known) if known else None,
        provider_reported_cost_usd=(
            sum((Decimal(c.provider_reported_cost_usd) for c in calls), Decimal(0))
            if calls and all(c.provider_reported_cost_usd is not None for c in calls) else None
        ),
        computed_cost_usd=cost, absorbed_cost_usd=absorbed_cost, absorbed_credits=credits,
        reason=reason, delivery_status=delivery_status,
        error_category=failed[-1].error_category if failed else None,
        fallback_attempted=fallback_attempted, fallback_outcome=fallback_outcome,
        requested_at=min(_utc(c.requested_at) for c in calls),
        failed_at=max((_utc(c.finished_at) for c in failed if c.finished_at), default=None),
        recorded_at=at,
    )
    session.add(row)
    return row


def _absorb_attempts(session, op, calls, *, reason, delivery_status, per_usd, at, delivered_attempt=None):
    """Absorb every not-yet-absorbed call, one evidence row per attempt."""
    done = _absorbed_call_ids(session, op.operation_id)
    pending = [c for c in calls if c.id not in done]
    attempts = sorted({c.attempt_number for c in pending})
    all_attempts = sorted({c.attempt_number for c in _calls(session, op.operation_id)})
    total = 0
    for attempt in attempts:
        group = [c for c in pending if c.attempt_number == attempt]
        later = [a for a in all_attempts if a > attempt]
        outcome = None
        if later:
            outcome = "delivered" if delivered_attempt in later else "undelivered"
        row = _absorb(session, op, group, reason=reason, delivery_status=delivery_status, per_usd=per_usd,
                      at=at, fallback_attempted=bool(later), fallback_outcome=outcome)
        total += int(row.absorbed_credits or 0)
    return total


def _locked_operation(session, operation_id):
    _require_read_committed(session)
    probe = session.get(AIBillingOperation, operation_id)
    if probe is None:
        raise AIBillingStateError("the operation was not authorized")
    lock_billing_account(session, probe.billing_account_id)
    op = session.execute(
        select(AIBillingOperation).where(AIBillingOperation.operation_id == operation_id).with_for_update()
    ).scalar_one()
    session.refresh(op)
    return op


def _bound_conversion(session, op):
    return _conversion(session.get(PricingPolicyVersion, op.pricing_policy_version_id))


def _finalization(op, *, replay, released=0, supplemental=0):
    return FinalizationResult(
        operation_id=op.operation_id, delivery_status=op.delivery_status, state=op.state,
        charged_credits=int(op.charged_credits or 0), absorbed_credits=int(op.absorbed_credits or 0),
        released_credits=released, supplemental_credits=supplemental, replay=replay,
    )


def _finalize(session, op, **values):
    """The operation row is finalized by exactly one update (the database guard's contract)."""
    for column, value in values.items():
        setattr(op, column, value)
    session.flush()


def _outcome_recorded(op, delivery_status, *, delivered_attempt_number=None):
    """Replay of the same outcome returns it; any other outcome is refused (one outcome per operation)."""
    if op.delivery_status is None:
        if op.state in ("capacity_denied", "finalized"):
            raise AIBillingStateError("the operation is already closed")
        return False
    if op.delivery_status == delivery_status and (
            delivery_status != "delivered" or op.delivered_attempt_number == delivered_attempt_number):
        return True
    if op.state == "expired" and op.delivery_status == "unsettled":
        return False  # a lapsed operation learns, once, what became of its response
    raise AIBillingStateError("the operation's delivery outcome is already recorded")


def _expire(session, op, at):
    """End a lapsed lease: release the hold, absorb every recorded call, charge nothing."""
    reservation = _reservation(session, op.operation_id, lock=True)
    released = _release_all(session, op, reservation, "expired", at)
    reservation.state, reservation.finalized_at = "expired", at
    absorbed = _absorb_attempts(
        session, op, _calls(session, op.operation_id), reason="reservation_expired",
        delivery_status="unsettled", per_usd=_bound_conversion(session, op), at=at,
    )
    _finalize(session, op, state="expired", finalized_at=at, delivery_status="unsettled", charged_credits=0,
              absorbed_credits=absorbed, finalization_evidence_json={"released_credits": released})
    return released


def _record_after_lapse(session, op, at, delivery_status, delivered_attempt_number=None):
    """What became of a response whose lease lapsed: recorded truthfully, never charged.

    The operation first ends exactly as expiry ends it (whether or not the
    cleanup job got there first), then records the runtime's answer once. No
    credits are held again and no ledger entry is written, so a response that
    arrives late is still preserved and delivered, at Jaspen's cost.
    """
    released = _expire(session, op, at) if op.state == "authorized" else 0
    _finalize(session, op, delivery_status=delivery_status, delivered_attempt_number=delivered_attempt_number)
    return _finalization(op, replay=False, released=released)


def settle_delivered_operation(session, *, operation_id, delivered_attempt_number):
    """Charge a delivered response once: the delivering attempt's reported usage only (D06).

    Settles at any time while the reservation lease is live, including after the
    original execution deadline (founder decision 2026-11-16). A response
    delivered after the lease lapsed is recorded as delivered without a charge:
    its credits were released, and they are never held or charged again.
    """
    op = _locked_operation(session, operation_id)
    if _outcome_recorded(op, "delivered", delivered_attempt_number=delivered_attempt_number):
        return _finalization(op, replay=True)
    at = _clock(session)
    calls = _calls(session, operation_id)
    delivering = [c for c in calls if c.attempt_number == delivered_attempt_number]
    if not delivering or delivering[-1].outcome != "succeeded":
        raise AIBillingError("the delivering attempt must end in a successful provider call")
    root = op.root_operation_id or op.operation_id
    already_settled = op.step_key in _completed_steps(session, root)
    if op.state == "expired" or at >= _utc(op.expires_at):
        done = _record_after_lapse(session, op, at, "delivered", delivered_attempt_number)
        if not already_settled:  # the step reached the customer: a resume never repeats it
            session.add(AIOperationCheckpoint(root_operation_id=root, step_key=op.step_key,
                                              operation_id=operation_id, charged_credits=0, completed_at=at))
            session.flush()
        return done
    per_usd = _bound_conversion(session, op)
    others = [c for c in calls if c.attempt_number != delivered_attempt_number]

    reservation = _reservation(session, operation_id, lock=True)
    uncertain = any(c.usage_label != "reported" for c in delivering)
    due = 0
    if not uncertain and not already_settled:
        due = _credits(_total_cost(session, delivering), per_usd)
    holds, reserved_total = _open_holds(session, reservation.id)
    held = sum(amount for _e, amount in holds)
    supplemental = 0
    if due > held:
        need = due - held
        lots = _spendable(session, op.billing_account_id, op.actor_user_id, at)
        room = int(reservation.authorized_amount) - reserved_total
        if need <= room and need <= sum(a for _l, a in lots):
            _hold(session, op, reservation, need, lots, round_number=2, at=at)
            supplemental = need
            holds, _total = _open_holds(session, reservation.id)
            held = sum(amount for _e, amount in holds)
    charge = min(due, held)
    above_cap = due - charge

    remaining = charge
    for entry, amount in holds:
        if remaining == 0:
            break
        take = min(amount, remaining)
        _append(
            session, op=op, lot_id=entry.lot_id, entry_type="settlement", available=0, held=-take,
            reservation_id=reservation.id, related_entry_id=entry.id,
            key=f"settlement:{operation_id}:{entry.id}", at=at, reason="ai_delivered_response",
            evidence={"delivered_attempt_number": delivered_attempt_number,
                      "pricing_policy_version_id": op.pricing_policy_version_id},
        )
        remaining -= take
    released = _release_all(session, op, reservation, "settled_remainder", at)
    reservation.state, reservation.finalized_at = ("settled" if charge else "released"), at

    absorbed = _absorb_attempts(session, op, others, reason="not_delivering_attempt",
                                delivery_status="undelivered", per_usd=per_usd, at=at,
                                delivered_attempt=delivered_attempt_number)
    if already_settled:
        absorbed += int(_absorb(session, op, delivering, reason="step_already_settled",
                                delivery_status="delivered", per_usd=per_usd, at=at).absorbed_credits or 0)
    elif uncertain:
        absorbed += int(_absorb(session, op, delivering, reason="uncertain_usage",
                                delivery_status="delivered", per_usd=per_usd, at=at).absorbed_credits or 0)
    elif above_cap:
        _absorb(session, op, delivering, reason="above_reservation_cap", delivery_status="delivered",
                per_usd=per_usd, at=at, charged_credits=charge)
        absorbed += above_cap
    if not already_settled:
        session.add(AIOperationCheckpoint(
            root_operation_id=root, step_key=op.step_key, operation_id=operation_id,
            charged_credits=charge, completed_at=at,
        ))
    _finalize(
        session, op, state="finalized", finalized_at=at, delivery_status="delivered",
        delivered_attempt_number=delivered_attempt_number, charged_credits=charge, absorbed_credits=absorbed,
        finalization_evidence_json={
            "due_credits": due, "supplemental_credits": supplemental, "released_credits": released,
            "uncertain_usage": uncertain, "step_already_settled": already_settled,
        },
    )
    return _finalization(op, replay=False, released=released, supplemental=supplemental)


def _close_without_charge(session, operation_id, *, delivery_status, reason):
    op = _locked_operation(session, operation_id)
    if _outcome_recorded(op, delivery_status):
        return _finalization(op, replay=True)
    calls = _calls(session, operation_id)
    if delivery_status == "no_billable_usage" and any(
        c.usage_label != "reported" or int(c.input_tokens or 0) or int(c.output_tokens or 0) for c in calls
    ):
        raise AIBillingStateError("provider usage was recorded; close the operation as delivered or undelivered")
    at = _clock(session)
    if op.state == "expired" or at >= _utc(op.expires_at):
        return _record_after_lapse(session, op, at, delivery_status)
    per_usd = _bound_conversion(session, op)
    reservation = _reservation(session, operation_id, lock=True)
    released = _release_all(session, op, reservation, reason, at)
    reservation.state, reservation.finalized_at = "released", at
    absorbed = _absorb_attempts(
        session, op, calls, reason="undelivered", delivery_status="undelivered", per_usd=per_usd, at=at,
    )
    _finalize(session, op, state="finalized", finalized_at=at, delivery_status=delivery_status,
              charged_credits=0, absorbed_credits=absorbed)
    return _finalization(op, replay=False, released=released)


def record_undelivered_operation(session, *, operation_id):
    """No response reached the customer: release everything; absorb all known usage.

    Allowed while the lease is live or after it lapsed (the runtime knows the
    response failed), until the operation has recorded another outcome. After
    a lapse the operation ends as expiry ends it, then records "undelivered".
    """
    return _close_without_charge(session, operation_id, delivery_status="undelivered", reason="undelivered")


def release_without_billable_usage(session, *, operation_id):
    """No provider-billable usage occurred: release the exact reservation, no settlement."""
    return _close_without_charge(session, operation_id, delivery_status="no_billable_usage",
                                 reason="no_billable_usage")


def expire_ai_operation(session, *, operation_id):
    """Recover an operation once its reservation lease lapsed.

    A lapsed lease means the worker stopped renewing the hold, so no charge can
    follow (settlement checks the same lease by the same clock). Expiry
    releases the hold, absorbs every recorded call, and leaves the delivery
    "unsettled": the runtime may still record, once, that the response was
    delivered or not, and that record is the same whether it comes before or
    after this cleanup. Nothing is ever charged after the lease lapsed.
    """
    op = _locked_operation(session, operation_id)
    if op.state == "expired":
        return _finalization(op, replay=True)
    if op.state != "authorized":
        raise AIBillingStateError("only a running operation can expire")
    at = _clock(session)
    if at < _utc(op.expires_at):
        raise AIBillingStateError("the reservation lease is still live")
    released = _expire(session, op, at)
    return _finalization(op, replay=False, released=released)
