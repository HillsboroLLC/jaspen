"""D18 row 17, I2: the modern financial-event family runtime (``financial_events``).

This is the only live module that reaches the inactive Phase 5.1-5.3, 7, 8 and 9
services for modern organizations. Nothing here runs for a legacy account, or while
its family is off. Legacy contexts keep the legacy handlers byte-for-byte.

**Webhook routing.** ``webhook_billing_account`` names the modern billing account that
a verified processor event belongs to. It checks, in order:
* the object's processor customer;
* the ``billing_account_id`` this runtime writes into processor metadata;
* for refund and dispute objects, which carry no customer, the customer of the
  payment they reference.
The check runs only when at least one modern organization exists, so legacy webhook
behavior is untouched otherwise. A modern event is recorded once in the Phase 5.1
inbox (``billing_inbox.record_event``) and never reaches legacy fulfillment.

**Processing.** ``process_events`` claims a bounded batch of inbox events. For each
event it re-fetches the authoritative processor object (D14.5) and applies it in one
transaction, together with ``mark_processed``:
* Phase 5.2 transactions and lines;
* Phase 4/6 activation and renewal funding;
* Phase 7 plan changes;
* Phase 8 seat funding and increases;
* Phase 9 purchases and refund or dispute cases.
A failure rolls the transaction back. The event is then marked retryable or
quarantined in a fresh transaction, never processed by an exception handler (D14.11).

**D5.** Only allocations that are exact from the processor's own evidence are applied:
zero, a full refund or dispute, or a single eligible line with no tax or fee. Every
other partial multi-line allocation is quarantined for manual review
(``allocation_manual_review``). Every subscription refund (no approved disposition)
and every dispute in the processor's ``charge_refunded`` state is quarantined (Q4).

**Time.** A subscription period payment is effective at the start of the processor
period it pays (D14.4: explicit effective time). The first paid period's start is
the subscription anchor. Our calendar-month boundaries must equal the processor's
period, or the event is quarantined rather than guessed.
"""

from datetime import datetime, timezone
import uuid

from sqlalchemy import exists, func, select
from sqlalchemy.exc import DBAPIError

from . import billing_cutover as bc
from . import billing_inbox as inbox
from . import billing_runtime_funding as funding
from .billing_allocations import RecurringAllocationError, RecurringAllocationRetryError, allocate_recurring_credits
from .billing_entitlements import add_calendar_months, monthly_period_bounds
from .billing_financial import FinancialInvariantError, record_financial_transaction
from .billing_financial_effects import (
    CASE_EVENT_TYPES,
    FinancialEffectDependencyError,
    FinancialEffectError,
    FinancialEffectPolicyRequiredError,
    FinancialEffectRetryError,
    fund_credit_purchase,
    record_and_apply_financial_case_event,
)
from .billing_financial_cases import FinancialCaseConcurrentUpdateError
from .billing_outbox import OutboxConcurrentUpdateError
from .billing_plan_changes import (
    ACTIVE_SCHEDULE_STATES,
    PlanChangeError,
    PlanChangeRetryError,
    activate_free_to_paid,
    apply_paid_upgrade,
    apply_scheduled_change,
    mark_scheduled_renewal_unpaid,
)
from .billing_seats import (
    SeatChangeError,
    SeatChangeRetryError,
    apply_paid_seat_increase,
    current_seat_commitment,
    open_seat_commitment,
    record_seat_funding_attribution,
    record_seat_renewal_funding,
)
from .models import (
    BillingAccount,
    BillingSubscription,
    EntitlementDefinition,
    EntitlementInstance,
    FinancialLine,
    FinancialTransaction,
    ScheduledPlanChange,
)
from .models_billing_identity import BillingModelAssignment


FAMILY = "financial_events"
PROVIDER = "stripe"
SYSTEM = funding.SYSTEM_ACTOR
INTERVAL_MONTHS = {"month": 1, "year": 12}
INTERVAL_NAMES = {"monthly": "month", "annual": "year"}
RETRYABLE_SQLSTATES = frozenset({"40001", "40P01", "55P03"})
DISPUTE_STATES = {
    "warning_needs_response": "opened", "warning_under_review": "opened", "needs_response": "opened",
    "under_review": "pending", "won": "won", "warning_closed": "won", "lost": "lost",
}
REFUND_EVENTS = frozenset({"refund.created", "refund.updated", "charge.refund.updated"})
DISPUTE_EVENTS = frozenset({"charge.dispute.created", "charge.dispute.updated", "charge.dispute.closed"})
SEAT_METADATA = ("jaspen_seat_command_id", "jaspen_seat_requested_by", "jaspen_seat_delta")


class Quarantine(Exception):
    """Permanent: the event needs manual review. ``code`` is the bounded inbox error code."""

    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


class Retry(Exception):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


# ---------------------------------------------------------------------------
# Processor access (injectable for tests; production never reaches this module)
# ---------------------------------------------------------------------------

def _plain(obj):
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if hasattr(obj, "to_dict"):
        obj = obj.to_dict()
    if isinstance(obj, dict):
        return {key: _plain(value) for key, value in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_plain(value) for value in obj]
    return obj


class StripeGateway:
    """Authoritative processor reads (D14.5). Every method returns plain dicts."""

    def __init__(self, stripe_module=None):
        if stripe_module is None:
            import stripe as stripe_module
        self.stripe = stripe_module

    def invoice(self, invoice_id):
        invoice = _plain(self.stripe.Invoice.retrieve(invoice_id))
        lines = _plain(self.stripe.Invoice.list_lines(invoice_id, limit=100))
        if lines.get("has_more"):
            raise Quarantine("invoice_line_limit", invoice_id)
        invoice["lines"] = {"data": lines.get("data") or []}
        return invoice

    def payment_intent(self, payment_intent_id):
        return _plain(self.stripe.PaymentIntent.retrieve(payment_intent_id))

    def refund(self, refund_id):
        return _plain(self.stripe.Refund.retrieve(refund_id))

    def dispute(self, dispute_id):
        return _plain(self.stripe.Dispute.retrieve(dispute_id))

    def subscription(self, subscription_id):
        return _plain(self.stripe.Subscription.retrieve(subscription_id))

    def invoice_for_payment_intent(self, payment_intent_id):
        payments = _plain(self.stripe.InvoicePayment.list(
            payment={"type": "payment_intent", "payment_intent": payment_intent_id}, limit=1))
        data = payments.get("data") or []
        return _sid(data[0].get("invoice")) if data else None

    def customer_for_payment(self, payment_intent_id=None, charge_id=None):
        if payment_intent_id:
            return _sid(self.payment_intent(payment_intent_id).get("customer"))
        if charge_id:
            return _sid(_plain(self.stripe.Charge.retrieve(charge_id)).get("customer"))
        return None


def _sid(value):
    if isinstance(value, dict):
        value = value.get("id")
    return str(value) if value else None


def _ts(value, field):
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise Quarantine("processor_time_missing", field)
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _utc(value):
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _iso(value):
    return _utc(value).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------------------
# Accounts and webhook routing
# ---------------------------------------------------------------------------

def _modern_account_for_customer(session, customer_id):
    if not customer_id:
        return None
    return session.execute(
        select(BillingAccount).join(BillingModelAssignment,
                                    BillingModelAssignment.billing_account_id == BillingAccount.id)
        .where(BillingAccount.processor == PROVIDER, BillingAccount.processor_customer_id == customer_id)
    ).scalar_one_or_none()


def _modern_account_by_id(session, account_id):
    if not account_id:
        return None
    return session.execute(
        select(BillingAccount).join(BillingModelAssignment,
                                    BillingModelAssignment.billing_account_id == BillingAccount.id)
        .where(BillingAccount.id == str(account_id))
    ).scalar_one_or_none()


def webhook_billing_account(session, event, *, gateway=None):
    """The modern billing account a verified event belongs to, or ``None`` (legacy path)."""
    with session.no_autoflush:
        if session.execute(select(BillingModelAssignment.id).limit(1)).first() is None:
            return None  # no modern organization exists: legacy behavior is untouched
        obj = ((event or {}).get("data") or {}).get("object") or {}
        customer = obj.get("id") if obj.get("object") == "customer" else _sid(obj.get("customer"))
        account = _modern_account_for_customer(session, customer)
        if account is not None:
            return account
        metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
        account = _modern_account_by_id(session, metadata.get("billing_account_id"))
        if account is not None:
            return account
        if customer is None and obj.get("object") in ("refund", "dispute"):
            gateway = gateway or StripeGateway()
            customer = gateway.customer_for_payment(_sid(obj.get("payment_intent")), _sid(obj.get("charge")))
            return _modern_account_for_customer(session, customer)
        return None


def context_for_account(session, account, *, family=FAMILY, config=None):
    """The dispatch contract for an account-resolved event (raises while the family is off)."""
    context = bc.modern_context(session, family=family, organization_id=account.organization_id, config=config)
    if context is None or context.billing_account_id != account.id:
        raise Quarantine("not_modern_account", account.id)
    return context


def record_modern_webhook(session, raw_body, event, account, *, config=None):
    """Record a modern account's verified event in the inbox once. The caller commits."""
    context_for_account(session, account, config=config)
    _row, outcome = inbox.record_event(session, raw_body, event)
    return outcome


# ---------------------------------------------------------------------------
# Catalog mapping (configured prices only)
# ---------------------------------------------------------------------------

def _price_map(app_config):
    mapping = {}
    for name, kind, interval in (("STRIPE_PRICE_IDS", "plan", "monthly"),
                                 ("STRIPE_ANNUAL_PRICE_IDS", "plan", "annual"),
                                 ("STRIPE_ADDITIONAL_SEAT_PRICE_IDS", "seat", "monthly"),
                                 ("STRIPE_ANNUAL_ADDITIONAL_SEAT_PRICE_IDS", "seat", "annual")):
        for plan_key, price_id in (app_config.get(name) or {}).items():
            if price_id:
                mapping[str(price_id)] = (kind, str(plan_key).lower(), interval)
    return mapping


def _line_price(line):
    pricing = (line.get("pricing") or {}).get("price_details") or {}
    return _sid(pricing.get("price")) or _sid(line.get("price"))


def _sum_amounts(items, field="amount"):
    total = 0
    for item in items or []:
        value = item.get(field)
        if isinstance(value, bool) or not isinstance(value, int):
            raise Quarantine("processor_amount_invalid")
        total += value
    return total


def _invoice_subscription(invoice):
    details = ((invoice.get("parent") or {}).get("subscription_details")) or invoice.get("subscription_details") or {}
    return _sid(details.get("subscription")) or _sid(invoice.get("subscription")), dict(details.get("metadata") or {})


def _invoice_lines(invoice, app_config):
    """Classify processor lines into Phase 5.2 lines (no money is derived or split)."""
    prices = _price_map(app_config)
    lines = []
    for raw in (invoice.get("lines") or {}).get("data") or []:
        amount = raw.get("amount")
        if isinstance(amount, bool) or not isinstance(amount, int):
            raise Quarantine("processor_amount_invalid", str(raw.get("id")))
        price = _line_price(raw)
        known = prices.get(price)
        if known is None:
            raise Quarantine("unknown_price", str(price))
        tax = _sum_amounts(raw.get("taxes") if raw.get("taxes") is not None else raw.get("tax_amounts"))
        discount = _sum_amounts(raw.get("discount_amounts"))
        period = raw.get("period") or {}
        lines.append({
            "id": _sid(raw.get("id")), "kind": known[0], "plan_key": known[1], "interval": known[2],
            "price": price, "quantity": int(raw.get("quantity") or 1), "amount": amount, "tax": tax,
            "discount": discount, "period_start": _ts(period.get("start"), "period.start"),
            "period_end": _ts(period.get("end"), "period.end"),
        })
    if not lines:
        raise Quarantine("invoice_without_lines")
    return lines


# ---------------------------------------------------------------------------
# Phase 5.2 recording
# ---------------------------------------------------------------------------

def _record(session, *, account, kind, object_type, object_id, version, effective_at, inbox_row, lines,
            effective_from_first=False):
    principal = sum(line["principal_minor"] for line in lines)
    tax = sum(line["tax_minor"] for line in lines)
    fee = sum(line["fee_minor"] for line in lines)
    discount = sum(line["discount_minor"] for line in lines)
    header = {
        "billing_account_id": account.id, "kind": kind, "provider": PROVIDER, "object_type": object_type,
        "object_id": object_id, "external_version": version, "effective_at": effective_at,
        "currency": account.currency, "principal_minor": principal, "tax_minor": tax, "fee_minor": fee,
        "discount_minor": discount, "gross_minor": principal + tax + fee + discount,
        "inbox_event_id": inbox_row.id,
    }
    existing = session.execute(select(FinancialTransaction).where(
        FinancialTransaction.provider == PROVIDER, FinancialTransaction.object_type == object_type,
        FinancialTransaction.object_id == object_id, FinancialTransaction.kind == kind,
        FinancialTransaction.external_version == version)).scalar_one_or_none()
    if existing is not None:
        # D14.3: the money object, not the event, is the business identity. A later delivery of the
        # same object converges on the first recording (and its evidence) or is a conflict.
        header["inbox_event_id"] = existing.inbox_event_id
        if effective_from_first:
            header["effective_at"] = _utc(existing.effective_at)
    transaction, _state = record_financial_transaction(session, header, lines)
    rows = session.execute(select(FinancialLine).where(
        FinancialLine.financial_transaction_id == transaction.id)).scalars().all()
    return transaction, {(row.external_line_id, row.line_kind): row for row in rows}


def _financial_line(raw, line_kind, account, *, subscription_id=None, instance_id=None):
    return {
        "external_line_id": raw["id"], "line_kind": line_kind, "source_type": "stripe_price",
        "source_id": raw["price"], "quantity": raw["quantity"], "currency": account.currency,
        "principal_minor": raw["amount"], "tax_minor": raw["tax"], "fee_minor": 0,
        "discount_minor": -raw["discount"], "subscription_id": subscription_id,
        "entitlement_instance_id": instance_id,
    }


def _source_transaction(session, account, object_type, object_id):
    return session.execute(select(FinancialTransaction).where(
        FinancialTransaction.billing_account_id == account.id, FinancialTransaction.provider == PROVIDER,
        FinancialTransaction.kind == "payment", FinancialTransaction.object_type == object_type,
        FinancialTransaction.object_id == object_id)).scalar_one_or_none()


# ---------------------------------------------------------------------------
# Subscriptions (Phase 4/6/7/8)
# ---------------------------------------------------------------------------

def _definition(session, plan_key, interval, at):
    definition = funding.current_definition(session, funding.plan_definition_key(plan_key, interval), at)
    if definition is None:
        raise Quarantine("definition_dependency", funding.plan_definition_key(plan_key, interval))
    return definition


def _term_end(anchor, interval, start):
    """The calendar term containing ``start`` (anchored months), as the processor must also see it."""
    index = funding.period_index_at(anchor, start)
    months = INTERVAL_MONTHS[interval]
    if index % months:
        raise Quarantine("processor_period_mismatch", "term does not start on an anchored boundary")
    begin = add_calendar_months(_utc(anchor), index)
    if begin != _utc(start):
        raise Quarantine("processor_period_mismatch", "processor period does not start on an anchored boundary")
    return add_calendar_months(_utc(anchor), index + months)


def _new_instance(session, account, subscription, definition, starts_at, ends_at, evidence):
    source_id = f"{subscription.external_subscription_id}:{_iso(starts_at)}:{definition.key}@{definition.version}"
    instance = session.execute(select(EntitlementInstance).where(
        EntitlementInstance.billing_account_id == account.id, EntitlementInstance.source_type == "subscription",
        EntitlementInstance.source_id == source_id)).scalar_one_or_none()
    if instance is None:
        instance = EntitlementInstance(
            id=str(uuid.uuid4()), billing_account_id=account.id, entitlement_definition_id=definition.id,
            subscription_id=subscription.id, state="proposed", starts_at=starts_at, ends_at=ends_at,
            source_type="subscription", source_id=source_id, approval_evidence_reference=evidence,
        )
        session.add(instance)
        session.flush()
    return instance


def _active_instance(session, subscription):
    return session.execute(select(EntitlementInstance).where(
        EntitlementInstance.subscription_id == subscription.id, EntitlementInstance.state == "active",
        EntitlementInstance.entitlement_definition_id == subscription.current_entitlement_definition_id,
    )).scalar_one_or_none()


def _seat_quantity_needed(definition):
    return (definition.capability_json or {}).get("capabilities", {}).get("included_seats") is not None


def _invoice_money_lines(account, lines, *, subscription, plan_instance, plan_line_ids):
    out = []
    for raw in lines:
        if raw["id"] in plan_line_ids:
            out.append(_financial_line(raw, "subscription", account, subscription_id=subscription.id,
                                       instance_id=plan_instance.id))
        elif raw["kind"] == "seat" and raw["amount"] > 0:
            out.append(_financial_line(raw, "seat", account, subscription_id=subscription.id))
        else:
            out.append(_financial_line(raw, "other", account, subscription_id=subscription.id))
    return out


def _reconcile_invoice(invoice, lines):
    total = sum(line["amount"] + line["tax"] - line["discount"] for line in lines)
    if total != invoice.get("total") or invoice.get("amount_paid") != invoice.get("total"):
        raise Quarantine("invoice_reconciliation", str(invoice.get("id")))


def _plan_lines(lines):
    return [line for line in lines if line["kind"] == "plan" and line["amount"] > 0]


def _open_seats(session, account, subscription, definition, plan_line, seat_lines, term, opened_at):
    if not _seat_quantity_needed(definition):
        return
    attributions = []
    attribution, _state = record_seat_funding_attribution(
        session, billing_account_id=account.id, subscription_id=subscription.id,
        financial_line_id=plan_line.id, seat_source="included", term_starts_at=term[0], term_ends_at=term[1],
        evidence_reference=f"stripe:invoice_line:{plan_line.external_line_id}", actor_type=SYSTEM[0],
        actor_id=SYSTEM[1])
    attributions.append(attribution)
    for line in seat_lines:
        attribution, _state = record_seat_funding_attribution(
            session, billing_account_id=account.id, subscription_id=subscription.id, financial_line_id=line.id,
            seat_source="purchased", term_starts_at=term[0], term_ends_at=term[1],
            evidence_reference=f"stripe:invoice_line:{line.external_line_id}", actor_type=SYSTEM[0],
            actor_id=SYSTEM[1], seats=int(line.quantity))
        attributions.append(attribution)
    return attributions


def _activate(session, account, row, invoice, lines, external_id, metadata):
    plans = _plan_lines(lines)
    if len(plans) != 1:
        raise Quarantine("activation_plan_line", f"{len(plans)} paid plan lines")
    plan = plans[0]
    interval = INTERVAL_NAMES[plan["interval"]]
    anchor = plan["period_start"]
    term_end = add_calendar_months(anchor, INTERVAL_MONTHS[interval])
    if term_end != plan["period_end"]:
        raise Quarantine("processor_period_mismatch", "processor period end differs from the anchored term")
    if metadata.get("billing_account_id") not in (None, account.id):
        raise Quarantine("metadata_account_mismatch")
    definition = _definition(session, plan["plan_key"], plan["interval"], anchor)
    subscription = session.execute(select(BillingSubscription).where(
        BillingSubscription.processor == PROVIDER,
        BillingSubscription.external_subscription_id == external_id)).scalar_one_or_none()
    if subscription is None:
        others = [i for i in funding._active_plan_instances(session, account.id) if i.source_type != "free"]
        if others:
            raise Quarantine("second_subscription", external_id)
        subscription = BillingSubscription(
            id=str(uuid.uuid4()), billing_account_id=account.id, processor=PROVIDER,
            external_subscription_id=external_id, interval=interval, anchor_at=anchor, term_starts_at=anchor,
            term_ends_at=term_end, state="incomplete", current_entitlement_definition_id=definition.id,
            origin_evidence_json={"inbox_event_id": row.id, "invoice_id": invoice["id"]},
        )
        session.add(subscription)
        session.flush()
    elif subscription.billing_account_id != account.id:
        raise Quarantine("subscription_account_mismatch")
    target = _new_instance(session, account, subscription, definition, anchor, term_end,
                           f"stripe:invoice:{invoice['id']}")
    transaction, by_key = _record(
        session, account=account, kind="payment", object_type="invoice", object_id=invoice["id"],
        version="paid", effective_at=anchor, inbox_row=row,
        lines=_invoice_money_lines(account, lines, subscription=subscription, plan_instance=target,
                                   plan_line_ids={plan["id"]}))
    plan_line = by_key[(plan["id"], "subscription")]
    funding.require_family()
    obligations = funding.placeholder_obligations
    if subscription.state in ("proposed", "incomplete"):
        free = funding.active_free_instance(session, account.id)
        if free is not None:
            activate_free_to_paid(
                session, billing_account_id=account.id, subscription_id=subscription.id,
                free_entitlement_instance_id=free.id, target_entitlement_instance_id=target.id,
                financial_line_id=plan_line.id, paid_at=anchor, actor_type=SYSTEM[0], actor_id=SYSTEM[1],
                change_delivery_obligations=obligations("plan_change_applied"),
                funding_delivery_obligations=obligations("credit_period_funded"))
        else:
            source = f"activation:{subscription.id}:{plan_line.id}"
            if target.state == "proposed":
                funding.transition_instance(session, target, "scheduled", "first_paid_approved", anchor, source)
            if target.state == "scheduled":
                funding.transition_instance(session, target, "active", "first_paid_activation", anchor, source)
            subscription.state = "active"
            session.flush()
    if target.state != "active":
        raise Quarantine("activation_state", target.state)
    allocate_recurring_credits(
        session, billing_account_id=account.id, entitlement_instance_id=target.id, period_index=0,
        opened_at=anchor, delivery_obligations=obligations("credit_period_funded"),
        financial_line_id=plan_line.id, actor_type=SYSTEM[0], actor_id=SYSTEM[1])
    seats = [by_key[(line["id"], "seat")] for line in lines if line["kind"] == "seat" and line["amount"] > 0]
    attributions = _open_seats(session, account, subscription, definition, plan_line, seats, (anchor, term_end),
                               anchor)
    if attributions and current_seat_commitment(session, subscription.id) is None:
        open_seat_commitment(
            session, billing_account_id=account.id, subscription_id=subscription.id,
            quantity=sum(a.seats for a in attributions), attribution_ids=[a.id for a in attributions],
            opened_at=anchor, actor_type=SYSTEM[0], actor_id=SYSTEM[1],
            delivery_obligations=obligations("seat_commitment_opened"))
    return "activated"


def _local_subscription(session, account, external_id):
    subscription = session.execute(select(BillingSubscription).where(
        BillingSubscription.processor == PROVIDER,
        BillingSubscription.external_subscription_id == external_id)).scalar_one_or_none()
    if subscription is None:
        raise Retry("subscription_not_recorded", external_id)  # its activation has not been applied yet
    if subscription.billing_account_id != account.id:
        raise Quarantine("subscription_account_mismatch")
    return subscription


def _active_schedule(session, subscription):
    return session.execute(select(ScheduledPlanChange).where(
        ScheduledPlanChange.subscription_id == subscription.id,
        ScheduledPlanChange.state.in_(ACTIVE_SCHEDULE_STATES))).scalar_one_or_none()


def _renew(session, account, row, invoice, lines, external_id):
    subscription = _local_subscription(session, account, external_id)
    plans = _plan_lines(lines)
    if len(plans) != 1:
        raise Quarantine("renewal_plan_line", f"{len(plans)} paid plan lines")
    plan = plans[0]
    start = plan["period_start"]
    months = INTERVAL_MONTHS[subscription.interval]
    if INTERVAL_NAMES[plan["interval"]] != subscription.interval:
        raise Quarantine("interval_change_unsupported")
    already = _utc(subscription.term_starts_at) == start
    if not already and _utc(subscription.term_ends_at) != start:
        raise Quarantine("renewal_gap", "the paid period does not follow the current term")
    end = add_calendar_months(start, months)
    if _term_end(subscription.anchor_at, subscription.interval, start) != end or plan["period_end"] != end:
        raise Quarantine("processor_period_mismatch")
    definition = _definition(session, plan["plan_key"], plan["interval"], start)
    index = funding.period_index_at(subscription.anchor_at, start)
    obligations = funding.placeholder_obligations
    schedule = _active_schedule(session, subscription)
    if schedule is not None and _utc(schedule.effective_at) == start:
        if schedule.kind != "downgrade" or schedule.target_entitlement_definition_id != definition.id:
            raise Quarantine("renewal_conflicts_with_schedule", schedule.kind)
        target = _new_instance(session, account, subscription, definition, start, end,
                               f"stripe:invoice:{invoice['id']}")
        _transaction, by_key = _record(
            session, account=account, kind="payment", object_type="invoice", object_id=invoice["id"],
            version="paid", effective_at=start, inbox_row=row,
            lines=_invoice_money_lines(account, lines, subscription=subscription, plan_instance=target,
                                       plan_line_ids={plan["id"]}))
        funding.require_family()
        if target.state == "proposed":
            funding.transition_instance(session, target, "scheduled", "scheduled_downgrade_approved", start,
                                        f"downgrade:{schedule.id}")
        apply_scheduled_change(
            session, scheduled_change_id=schedule.id, target_entitlement_instance_id=target.id,
            financial_line_id=by_key[(plan["id"], "subscription")].id, period_index=index, applied_at=start,
            actor_type=SYSTEM[0], actor_id=SYSTEM[1], change_delivery_obligations=obligations("plan_change_applied"),
            funding_delivery_obligations=obligations("credit_period_funded"))
        return "downgraded"
    if schedule is not None and _utc(schedule.effective_at) < start:
        raise Quarantine("schedule_missed", schedule.id)
    if definition.id != subscription.current_entitlement_definition_id:
        raise Quarantine("renewal_definition_changed")
    current = _active_instance(session, subscription)
    target = _new_instance(session, account, subscription, definition, start, end, f"stripe:invoice:{invoice['id']}")
    _transaction, by_key = _record(
        session, account=account, kind="payment", object_type="invoice", object_id=invoice["id"],
        version="paid", effective_at=start, inbox_row=row,
        lines=_invoice_money_lines(account, lines, subscription=subscription, plan_instance=target,
                                   plan_line_ids={plan["id"]}))
    funding.require_family()
    plan_line = by_key[(plan["id"], "subscription")]
    seats = [by_key[(line["id"], "seat")] for line in lines if line["kind"] == "seat" and line["amount"] > 0]
    attributions = _open_seats(session, account, subscription, definition, plan_line, seats, (start, end), start) \
        if current_seat_commitment(session, subscription.id) is not None else None
    if not already:
        subscription.term_starts_at = start
        subscription.term_ends_at = end
        if subscription.state == "past_due":
            subscription.state = "active"
        session.flush()
    source = f"renewal:{subscription.id}:{_iso(start)}"
    if current is not None and current.id != target.id:
        funding.transition_instance(session, current, "expired", "term_renewed", start, source)
    if target.state == "proposed":
        funding.transition_instance(session, target, "scheduled", "renewal_paid", start, source)
    if target.state == "scheduled":
        funding.transition_instance(session, target, "active", "renewal_activated", start, source)
    allocate_recurring_credits(
        session, billing_account_id=account.id, entitlement_instance_id=target.id, period_index=index,
        opened_at=start, delivery_obligations=obligations("credit_period_funded"), financial_line_id=plan_line.id,
        actor_type=SYSTEM[0], actor_id=SYSTEM[1])
    if attributions:
        record_seat_renewal_funding(
            session, billing_account_id=account.id, subscription_id=subscription.id,
            attribution_ids=[a.id for a in attributions], term_starts_at=start, recorded_at=start,
            actor_id=SYSTEM[1], delivery_obligations=obligations("seat_term_funded"))
    return "renewed"


def _update(session, account, row, invoice, lines, external_id, metadata):
    subscription = _local_subscription(session, account, external_id)
    paid_at = _ts((invoice.get("status_transitions") or {}).get("paid_at"), "status_transitions.paid_at")
    if not (_utc(subscription.term_starts_at) <= paid_at < _utc(subscription.term_ends_at)):
        raise Quarantine("update_outside_term")
    current_definition = session.get(EntitlementDefinition, subscription.current_entitlement_definition_id)
    plans = _plan_lines(lines)
    seats = [line for line in lines if line["kind"] == "seat" and line["amount"] > 0]
    if len(plans) > 1 or (plans and seats) or not (plans or seats):
        raise Quarantine("unsupported_subscription_update")
    obligations = funding.placeholder_obligations
    if plans:
        plan = plans[0]
        if INTERVAL_NAMES[plan["interval"]] != subscription.interval:
            raise Quarantine("interval_change_unsupported")
        definition = _definition(session, plan["plan_key"], plan["interval"], paid_at)
        if int(definition.funding_policy_json["credit_amount"]) <= int(current_definition.funding_policy_json[
                "credit_amount"]):
            raise Quarantine("unsupported_subscription_update", "a paid update must be an upgrade")
        prior = _active_instance(session, subscription)
        if prior is None:
            prior = session.execute(select(EntitlementInstance).where(
                EntitlementInstance.subscription_id == subscription.id,
                EntitlementInstance.entitlement_definition_id == definition.id,
                EntitlementInstance.state == "active")).scalar_one_or_none()
            if prior is None:
                raise Quarantine("upgrade_without_active_entitlement")
        target = _new_instance(session, account, subscription, definition, paid_at, _utc(subscription.term_ends_at),
                               f"stripe:invoice:{invoice['id']}")
        _transaction, by_key = _record(
            session, account=account, kind="payment", object_type="invoice", object_id=invoice["id"],
            version="paid", effective_at=paid_at, inbox_row=row,
            lines=_invoice_money_lines(account, lines, subscription=subscription, plan_instance=target,
                                       plan_line_ids={plan["id"]}))
        funding.require_family()
        upgraded_prior = prior if prior.id != target.id else None
        apply_paid_upgrade(
            session, billing_account_id=account.id, subscription_id=subscription.id,
            prior_entitlement_instance_id=(upgraded_prior or prior).id, target_entitlement_instance_id=target.id,
            financial_line_id=by_key[(plan["id"], "subscription")].id, paid_at=paid_at,
            period_index=funding.period_index_at(subscription.anchor_at, paid_at), actor_type=SYSTEM[0],
            actor_id=SYSTEM[1], delivery_obligations=obligations("plan_change_applied"))
        return "upgraded"
    command = {key: str(metadata.get(key) or "").strip() for key in SEAT_METADATA}
    if not all(command.values()):
        raise Quarantine("seat_command_unattributed")
    try:
        delta = int(command["jaspen_seat_delta"])
    except ValueError as exc:
        raise Quarantine("seat_command_unattributed") from exc
    _transaction, by_key = _record(
        session, account=account, kind="payment", object_type="invoice", object_id=invoice["id"], version="paid",
        effective_at=paid_at, inbox_row=row,
        lines=_invoice_money_lines(account, lines, subscription=subscription, plan_instance=None, plan_line_ids=set()))
    if len(seats) != 1:
        raise Quarantine("unsupported_subscription_update", "one seat line is required")
    attribution, _state = record_seat_funding_attribution(
        session, billing_account_id=account.id, subscription_id=subscription.id,
        financial_line_id=by_key[(seats[0]["id"], "seat")].id, seat_source="purchased", term_starts_at=paid_at,
        term_ends_at=_utc(subscription.term_ends_at), evidence_reference=f"stripe:invoice:{invoice['id']}",
        actor_type=SYSTEM[0], actor_id=SYSTEM[1], seats=delta)
    apply_paid_seat_increase(
        session, billing_account_id=account.id, subscription_id=subscription.id,
        client_command_id=command["jaspen_seat_command_id"], seat_delta=delta, attribution_ids=[attribution.id],
        requested_at=paid_at, paid_at=paid_at, requested_by_user_id=command["jaspen_seat_requested_by"],
        delivery_obligations=obligations("seat_change_applied"))
    return "seats_increased"


def _invoice_paid(session, row, gateway, app_config, config):
    invoice = gateway.invoice(row.object_id)
    if invoice.get("status") != "paid":
        raise Quarantine("invoice_not_paid", str(invoice.get("status")))
    account = _account_from_object(session, invoice)
    context_for_account(session, account, config=config)
    external_id, metadata = _invoice_subscription(invoice)
    if not external_id:
        raise Quarantine("invoice_without_subscription")
    lines = _invoice_lines(invoice, app_config)
    _reconcile_invoice(invoice, lines)
    reason = invoice.get("billing_reason")
    if reason == "subscription_create":
        return _activate(session, account, row, invoice, lines, external_id, metadata)
    if reason == "subscription_cycle":
        return _renew(session, account, row, invoice, lines, external_id)
    if reason == "subscription_update":
        return _update(session, account, row, invoice, lines, external_id, metadata)
    raise Quarantine("unsupported_billing_reason", str(reason))


def _invoice_failed(session, row, gateway, config):
    invoice = gateway.invoice(row.object_id)
    account = _account_from_object(session, invoice)
    context_for_account(session, account, config=config)
    external_id, _metadata = _invoice_subscription(invoice)
    if not external_id:
        return "ignored"
    subscription = _local_subscription(session, account, external_id)
    if invoice.get("billing_reason") != "subscription_cycle":
        return "ignored"  # a failed upgrade or seat payment grants and changes nothing
    if subscription.state == "active":
        subscription.state = "past_due"
        session.flush()
    schedule = _active_schedule(session, subscription)
    if schedule is not None and schedule.kind == "downgrade" and schedule.state == "pending":
        mark_scheduled_renewal_unpaid(
            session, scheduled_change_id=schedule.id, observed_at=bc._database_now(session),
            actor_type=SYSTEM[0], actor_id=SYSTEM[1],
            delivery_obligations=funding.placeholder_obligations("plan_change_scheduled"))
    return "renewal_unpaid"


def _subscription_ended(session, row, gateway, config):
    processor = gateway.subscription(row.object_id)
    account = _account_from_object(session, processor)
    context_for_account(session, account, config=config)
    subscription = _local_subscription(session, account, row.object_id)
    if subscription.state in ("cancelled", "expired"):
        return "ignored"
    schedule = _active_schedule(session, subscription)
    if schedule is None or schedule.kind != "cancellation":
        raise Quarantine("unscheduled_subscription_end")
    apply_scheduled_change(
        session, scheduled_change_id=schedule.id, target_entitlement_instance_id=None, financial_line_id=None,
        period_index=funding.period_index_at(subscription.anchor_at, _utc(schedule.effective_at)),
        applied_at=_utc(schedule.effective_at), actor_type=SYSTEM[0], actor_id=SYSTEM[1],
        change_delivery_obligations=funding.placeholder_obligations("plan_change_applied"),
        funding_delivery_obligations=())
    return "cancelled"


# ---------------------------------------------------------------------------
# Credit packs and cases (Phase 9)
# ---------------------------------------------------------------------------

def _account_from_object(session, obj):
    account = _modern_account_for_customer(session, _sid(obj.get("customer")))
    if account is None:
        raise Quarantine("not_modern_customer")
    metadata = obj.get("metadata") if isinstance(obj.get("metadata"), dict) else {}
    if metadata.get("billing_account_id") not in (None, "", account.id):
        raise Quarantine("metadata_account_mismatch")
    return account


def _pack_paid(session, row, gateway, config):
    intent = gateway.payment_intent(row.object_id)
    metadata = intent.get("metadata") or {}
    if metadata.get("checkout_type") != "credit_pack":
        return "ignored"  # a subscription invoice's payment: the invoice event carries it
    if intent.get("status") != "succeeded":
        raise Quarantine("payment_not_succeeded", str(intent.get("status")))
    account = _account_from_object(session, intent)
    context_for_account(session, account, config=config)
    funding.require_family()
    paid_at = _utc(row.provider_created_at)
    pack_key = str(metadata.get("pack_key") or "")
    definition = funding.current_definition(session, funding.pack_definition_key(pack_key), paid_at)
    if definition is None:
        raise Quarantine("definition_dependency", funding.pack_definition_key(pack_key))
    terms = definition.funding_policy_json["purchase"]
    amount = intent.get("amount_received")
    if amount != terms["unit_principal_minor"] * terms["quantity"] or intent.get("currency") != account.currency:
        raise Quarantine("pack_amount_mismatch")
    _transaction, by_key = _record(
        session, account=account, kind="payment", object_type="payment_intent", object_id=intent["id"],
        version="succeeded", effective_at=paid_at, inbox_row=row, effective_from_first=True, lines=[{
            "external_line_id": f"{intent['id']}:pack", "line_kind": "credit_pack",
            "source_type": funding.PACK_SOURCE_TYPE, "source_id": pack_key, "quantity": terms["quantity"],
            "currency": account.currency, "principal_minor": amount, "tax_minor": 0, "fee_minor": 0,
            "discount_minor": 0, "subscription_id": None, "entitlement_instance_id": None}])
    fund_credit_purchase(
        session, billing_account_id=account.id, financial_line_id=by_key[(f"{intent['id']}:pack", "credit_pack")].id,
        entitlement_definition_id=definition.id, funded_at=bc._database_now(session), actor_type=SYSTEM[0],
        actor_id=SYSTEM[1], delivery_obligations=funding.placeholder_obligations("credit_purchase_funded"))
    return "pack_funded"


def resolve_case_allocations(session, source, amount):
    """D5: ``(allocations, cumulative, basis)`` only when exact from processor evidence; else quarantine."""
    lines = session.execute(select(FinancialLine).where(
        FinancialLine.financial_transaction_id == source.id).order_by(FinancialLine.id)).scalars().all()
    eligible = [line for line in lines if line.line_kind not in ("tax", "fee", "discount")
                and int(line.principal_minor) + int(line.discount_minor) > 0]
    if amount == 0:
        return [], 0, "none"
    if amount == int(source.gross_minor) and eligible:
        allocations = [{"financial_line_id": line.id,
                        "attributed_principal_minor": int(line.principal_minor) + int(line.discount_minor)}
                       for line in eligible]
        return allocations, sum(a["attributed_principal_minor"] for a in allocations), "full"
    if (len(eligible) == 1 and len(lines) == 1 and int(source.tax_minor) == 0 and int(source.fee_minor) == 0
            and 0 < amount <= int(eligible[0].principal_minor) + int(eligible[0].discount_minor)):
        return [{"financial_line_id": eligible[0].id, "attributed_principal_minor": amount}], amount, "single_line"
    raise Quarantine("allocation_manual_review", "no authoritative processor line allocation (D5)")


def _case_source(session, account, obj, gateway):
    payment_intent = _sid(obj.get("payment_intent"))
    source = _source_transaction(session, account, "payment_intent", payment_intent) if payment_intent else None
    if source is not None:
        return source
    invoice_id = gateway.invoice_for_payment_intent(payment_intent) if payment_intent else None
    source = _source_transaction(session, account, "invoice", invoice_id) if invoice_id else None
    if source is None:
        raise Retry("case_source_not_recorded")  # D14.8: line attribution must finish first
    return source


def _apply_case(session, row, account, source, *, case_type, obj, state, amount):
    allocations, cumulative, basis = resolve_case_allocations(session, source, amount)
    version = row.event_id
    event_transaction, _lines = _record(
        session, account=account, kind=case_type, object_type=case_type, object_id=obj["id"], version=version,
        effective_at=_utc(row.provider_created_at), inbox_row=row, lines=[{
            "external_line_id": f"{obj['id']}:{version}", "line_kind": "other",
            "source_type": f"stripe_{case_type}", "source_id": obj["id"], "quantity": 1,
            "currency": account.currency, "principal_minor": -cumulative, "tax_minor": 0, "fee_minor": 0,
            "discount_minor": 0, "subscription_id": None, "entitlement_instance_id": None}])
    case = {
        "billing_account_id": account.id, "provider": PROVIDER, "case_type": case_type,
        "case_object_id": obj["id"], "source_financial_transaction_id": source.id,
        "financial_transaction_id": event_transaction.id, "state": state, "disposition": None,
        "cumulative_principal_minor": cumulative, "line_allocations": allocations,
    }
    funding.require_family()
    _case, _event, record_state, _evaluations = record_and_apply_financial_case_event(
        session, case, applied_at=bc._database_now(session), actor_type=SYSTEM[0], actor_id=SYSTEM[1],
        delivery_obligations=funding.placeholder_obligations(CASE_EVENT_TYPES[state]))
    return f"{case_type}_{record_state}"


def _has_case(session, case_type, object_id):
    from .models_billing_phase5 import FinancialCase

    return session.execute(select(exists().where(
        FinancialCase.case_type == case_type, FinancialCase.case_object_id == object_id))).scalar()


def _refund(session, row, gateway, config):
    if row.object_type != "refund":
        return "ignored"
    refund = gateway.refund(row.object_id)
    account = _account_for_payment_object(session, refund, gateway)
    context_for_account(session, account, config=config)
    source = _case_source(session, account, refund, gateway)
    if any(line.line_kind == "subscription" for line in session.execute(select(FinancialLine).where(
            FinancialLine.financial_transaction_id == source.id)).scalars()):
        raise Quarantine("subscription_refund_review", "no approved subscription refund disposition (Q4)")
    status = refund.get("status")
    if status in ("pending", "requires_action"):
        return "ignored"  # a later refund event carries the outcome
    if status in ("failed", "canceled"):
        if not _has_case(session, "refund", refund["id"]):
            return "ignored"
        amount = 0
    elif status == "succeeded":
        amount = refund.get("amount")
    else:
        raise Quarantine("refund_status_unknown", str(status))
    return _apply_case(session, row, account, source, case_type="refund", obj=refund, state="refund_recorded",
                       amount=amount)


def _account_for_payment_object(session, obj, gateway):
    account = _modern_account_for_customer(session, gateway.customer_for_payment(
        _sid(obj.get("payment_intent")), _sid(obj.get("charge"))))
    if account is None:
        raise Quarantine("not_modern_customer")
    return account


def _dispute(session, row, gateway, config):
    if row.object_type != "dispute":
        return "ignored"
    dispute = gateway.dispute(row.object_id)
    status = dispute.get("status")
    if status == "charge_refunded":
        raise Quarantine("dispute_charge_refunded_review", "no approved policy (Q4)")
    state = DISPUTE_STATES.get(status)
    if state is None:
        raise Quarantine("dispute_status_unknown", str(status))
    account = _account_for_payment_object(session, dispute, gateway)
    context_for_account(session, account, config=config)
    source = _case_source(session, account, dispute, gateway)
    return _apply_case(session, row, account, source, case_type="dispute", obj=dispute, state=state,
                       amount=dispute.get("amount"))


# ---------------------------------------------------------------------------
# The processor
# ---------------------------------------------------------------------------

def _sqlstate(exc):
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


def classify_failure(exc):
    """``("retry"|"quarantine", code)`` for an exception raised while applying one event."""
    import stripe

    chain = []
    cursor = exc
    while cursor is not None and len(chain) < 6:
        chain.append(cursor)
        cursor = cursor.__cause__
    for item in chain:
        if isinstance(item, Retry):
            return "retry", item.code
        if isinstance(item, Quarantine):
            return "quarantine", item.code
        if isinstance(item, bc.BillingFamilyDisabledError):
            return "retry", "family_disabled"
        if isinstance(item, (RecurringAllocationRetryError, PlanChangeRetryError, SeatChangeRetryError,
                             FinancialEffectRetryError, funding.FundingRetryError, inbox.InboxRetryError,
                             OutboxConcurrentUpdateError, FinancialCaseConcurrentUpdateError)):
            return "retry", type(item).__name__
        if isinstance(item, DBAPIError) and _sqlstate(item) in RETRYABLE_SQLSTATES:
            return "retry", f"sqlstate_{_sqlstate(item)}"
        if isinstance(item, (stripe.error.APIConnectionError, stripe.error.RateLimitError,
                             stripe.error.APIError)):
            return "retry", "processor_unavailable"
    if isinstance(exc, FinancialEffectPolicyRequiredError):
        return "quarantine", "manual_review_policy"
    if isinstance(exc, FinancialEffectDependencyError):
        return "quarantine", "definition_dependency"
    if isinstance(exc, (FinancialInvariantError, FinancialEffectError, RecurringAllocationError, PlanChangeError,
                        SeatChangeError, funding.FundingRuntimeError, bc.BillingCutoverError, DBAPIError,
                        stripe.error.StripeError)):
        return "quarantine", f"invariant:{type(exc).__name__}"[:120]
    return "quarantine", f"unexpected:{type(exc).__name__}"[:120]


def apply_event(session, row, *, gateway, app_config, config=None):
    """Apply one claimed inbox event in the caller's transaction. Returns a short outcome."""
    if row.event_type == "invoice.paid":
        return _invoice_paid(session, row, gateway, app_config, config)
    if row.event_type == "invoice.payment_failed":
        return _invoice_failed(session, row, gateway, config)
    if row.event_type == "payment_intent.succeeded":
        return _pack_paid(session, row, gateway, config)
    if row.event_type in REFUND_EVENTS:
        return _refund(session, row, gateway, config)
    if row.event_type in DISPUTE_EVENTS:
        return _dispute(session, row, gateway, config)
    if row.event_type == "customer.subscription.deleted":
        return _subscription_ended(session, row, gateway, config)
    return "ignored"  # commands own every other transition; the event is evidence only


def process_events(session, *, limit, gateway=None, app_config=None, config=None):
    """Claim and apply up to ``limit`` inbox events, one transaction each. Idempotent and bounded."""
    from flask import current_app

    bc._require_family(FAMILY, config)
    gateway = gateway or StripeGateway()
    app_config = app_config if app_config is not None else current_app.config
    session.rollback()
    summary = {"claimed": 0, "processed": 0, "retryable": 0, "quarantined": 0, "lost_claims": 0, "events": []}
    for _ in range(int(limit)):
        row = inbox.claim_next_event(session)
        if row is None:
            session.rollback()
            break
        event_pk, token, event_id = row.id, row.attempt_count, row.event_id
        session.commit()
        summary["claimed"] += 1
        try:
            row = session.get(inbox.ExternalEventInbox, event_pk)
            outcome = apply_event(session, row, gateway=gateway, app_config=app_config, config=config)
            inbox.mark_processed(session, event_pk, token)
            session.commit()
            summary["processed"] += 1
            summary["events"].append({"event_id": event_id, "outcome": outcome})
            continue
        except inbox.StaleClaimError:
            session.rollback()
            summary["lost_claims"] += 1
            continue
        except Exception as exc:  # noqa: BLE001 - every failure is recorded on the event (D14.11)
            session.rollback()
            decision, code = classify_failure(exc)
        try:
            if decision == "retry":
                inbox.mark_retryable(session, event_pk, token, code[:120])
            else:
                inbox.mark_quarantined(session, event_pk, code[:120], claim_token=token)
            session.commit()
        except inbox.StaleClaimError:
            session.rollback()
            summary["lost_claims"] += 1
            continue
        summary["retryable" if decision == "retry" else "quarantined"] += 1
        summary["events"].append({"event_id": event_id, "outcome": decision, "code": code})
    return summary


# ---------------------------------------------------------------------------
# Account commands (the routes' modern handlers; the routes own request and response shapes)
# ---------------------------------------------------------------------------

class CommandError(Exception):
    """A modern account command is refused. ``status`` is the HTTP status the route answers with."""

    def __init__(self, message, status=400, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


def require_billing_authority(session, context, user_id, roles=("billing_owner", "billing_admin")):
    from .models import BillingRoleGrant
    from sqlalchemy import or_

    at = bc._database_now(session)
    grant = session.execute(select(BillingRoleGrant.id).where(
        BillingRoleGrant.billing_account_id == context.billing_account_id, BillingRoleGrant.user_id == str(user_id),
        BillingRoleGrant.role.in_(roles), BillingRoleGrant.state == "active", BillingRoleGrant.starts_at <= at,
        or_(BillingRoleGrant.ends_at.is_(None), BillingRoleGrant.ends_at > at))).first()
    if grant is None:
        raise CommandError("Only an organization billing owner can manage billing.", 403)


def ensure_processor_customer(session, context, user, stripe_module):
    """The billing account's processor customer: created once, bound with ``bind_processor_customer``.

    The creation uses a stable processor idempotency key, so a retry after a lost
    response returns the same customer, and ``billing_account_id`` is in its metadata.
    """
    account = session.get(BillingAccount, context.billing_account_id)
    if account.processor_customer_id:
        return account.processor_customer_id
    from .models import Organization

    organization = session.get(Organization, context.organization_id)
    customer = stripe_module.Customer.create(
        name=organization.name, email=user.email,
        metadata={"billing_account_id": account.id, "organization_id": context.organization_id},
        idempotency_key=f"jaspen-billing-account-customer:{account.id}",
    )
    bc.bind_processor_customer(session, billing_account_id=account.id, processor=PROVIDER,
                               processor_customer_id=customer.id, actor_user_id=str(user.id))
    session.commit()
    return customer.id


def processor_metadata(context, **values):
    """Processor metadata for a modern object: the account always, never a legacy ``user_id``."""
    metadata = {"billing_account_id": context.billing_account_id, "organization_id": context.organization_id}
    metadata.update({key: str(value) for key, value in values.items()})
    return metadata


def account_subscription(session, context, states=("active", "past_due", "cancel_at_period_end")):
    return session.execute(select(BillingSubscription).where(
        BillingSubscription.billing_account_id == context.billing_account_id,
        BillingSubscription.processor == PROVIDER, BillingSubscription.state.in_(states),
    ).order_by(BillingSubscription.created_at.desc())).scalars().first()


def subscription_plan(session, subscription):
    definition = session.get(EntitlementDefinition, subscription.current_entitlement_definition_id)
    capabilities = (definition.capability_json or {}).get("capabilities", {})
    return definition, capabilities.get("plan_key"), capabilities.get("interval")


def require_definition(session, plan_key, interval, at=None):
    at = at or bc._database_now(session)
    definition = funding.current_definition(session, funding.plan_definition_key(plan_key, interval), at)
    if definition is None:
        raise CommandError(f"No approved {interval} billing definition for '{plan_key}'.", 409)
    return definition


def paid_term_in_force(session, context):
    subscription = account_subscription(session, context)
    at = bc._database_now(session)
    if subscription is None or not (_utc(subscription.term_starts_at) <= at < _utc(subscription.term_ends_at)):
        return None
    return subscription


def schedule_change(session, context, subscription, *, kind, user_id, target_definition=None):
    """Phase 7 downgrade or cancellation at the current term end, by an authorized member. Not committed."""
    from .billing_plan_changes import schedule_plan_change

    require_billing_authority(session, context, user_id)
    effective = _utc(subscription.term_ends_at)
    target_id = target_definition.id if target_definition is not None else None
    active = _active_schedule(session, subscription)
    if active is not None and (active.kind, active.target_entitlement_definition_id) == (kind, target_id):
        return active  # the same change is already scheduled: a repeated command changes nothing
    # One command identity per distinct request: a resumed cancellation can be scheduled again.
    sequence = session.execute(select(func.count()).select_from(ScheduledPlanChange).where(
        ScheduledPlanChange.subscription_id == subscription.id)).scalar_one()
    command = f"{kind}:{subscription.id}:{target_id or 'none'}:{_iso(effective)}:{sequence}"
    try:
        change, _state = schedule_plan_change(
            session, billing_account_id=context.billing_account_id, subscription_id=subscription.id,
            client_command_id=command, kind=kind, target_entitlement_definition_id=target_id,
            requested_at=bc._database_now(session), effective_at=effective, compatible_supersede=True,
            actor_type="user", actor_id=str(user_id),
            delivery_obligations=funding.placeholder_obligations("plan_change_scheduled"))
    except PlanChangeError as exc:
        raise CommandError(str(exc), 409) from exc
    return change


def resume_change(session, context, subscription, *, user_id):
    from .billing_plan_changes import resume_cancellation

    require_billing_authority(session, context, user_id)
    schedule = _active_schedule(session, subscription)
    if schedule is None or schedule.kind != "cancellation":
        raise CommandError("No scheduled cancellation to resume.", 400)
    try:
        resume_cancellation(session, scheduled_change_id=schedule.id, resumed_at=bc._database_now(session),
                            actor_type="user", actor_id=str(user_id),
                            delivery_obligations=funding.placeholder_obligations("plan_change_superseded"))
    except PlanChangeError as exc:
        raise CommandError(str(exc), 409) from exc


def pack_funding_state(session, context, payment_intent_id):
    """Whether a modern credit-pack payment has been funded (a pure read)."""
    from .models_billing_phase9 import CreditPurchaseFunding

    source = session.execute(select(FinancialTransaction).where(
        FinancialTransaction.billing_account_id == context.billing_account_id,
        FinancialTransaction.object_type == "payment_intent",
        FinancialTransaction.object_id == payment_intent_id)).scalar_one_or_none()
    if source is None:
        return None
    rows = session.execute(select(CreditPurchaseFunding).join(
        FinancialLine, FinancialLine.id == CreditPurchaseFunding.financial_line_id
    ).where(FinancialLine.financial_transaction_id == source.id)).scalars().all()
    return sum(int(row.credit_amount) for row in rows) if rows else None


def seat_state(session, context, subscription):
    """The commitment and occupancy of a seat plan (pure reads)."""
    from .billing_seats import included_seats_for_definition, seat_occupancy

    definition = session.get(EntitlementDefinition, subscription.current_entitlement_definition_id)
    commitment = current_seat_commitment(session, subscription.id)
    return {
        "included": included_seats_for_definition(definition),
        "current": int(commitment.quantity) if commitment is not None else None,
        "used": seat_occupancy(session, context.organization_id),
    }
