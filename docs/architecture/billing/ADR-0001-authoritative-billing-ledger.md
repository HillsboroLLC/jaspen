# ADR-0001: Authoritative Billing, Entitlement, and Credit Boundaries

## D01 Final ADR

Status: **Proposed**

Decision owners: Product and Engineering

Decision date: pending review

Implementation authorization: none

### Context

Current billing state is spread across `users`, `organizations.settings`,
`users.ui_preferences`, `payments`, `account_entitlements`,
`persistent_credit_grants`, `persistent_credit_transactions`,
`stripe_webhook_events`, `usage_events`, `ai_operations`, and live Stripe
objects. Helpers that sound like resolvers also write balances and reset dates.
Plan, capability, funding, seat, admin, and organization ownership are coupled
through `User.subscription_plan` and the current organization owner.

This makes otherwise valid local fixes unsafe. For example, PR #27 prevents one
admin reset path, but the same balance is still mutated by authentication,
billing status, organization resolution, webhooks, scheduled reset jobs,
admin tools, and AI settlement. A durable correction requires one authority per
kind of truth and explicit event-driven state transitions.

### Decision

Jaspen will use the following boundaries:

1. **Billing Account Authority** owns the explicit payer/customer relationship,
   personal or organization ownership, processor identifiers, currency, tax
   context, and account status. A user or organization may own a billing
   account; ownership never depends on whichever organization is active.
2. **Financial Transaction Authority** owns invoices, invoice lines, payments,
   refunds, disputes, recoveries, taxes, fees, discounts, and processor
   evidence. Money records are immutable facts plus append-only corrections.
3. **Entitlement Authority** owns entitlement definitions and instances,
   effective intervals, plan/contract capabilities, scheduled plan changes,
   and seat commitments. Enterprise entitlement requires an executed,
   organization-owned contract.
4. **Credit Ledger Authority** owns every funded credit lot and every credit
   movement. Its entries are append-only. Balances are sums of eligible ledger
   entries, never mutable counters.
5. **AI Operation Authority** owns one customer-visible operation, its request
   identity, validation outcome, provider attempts, reservation reference, and
   settlement reference. It never owns a balance.
6. **Projection Authority** builds read models for API/UI consumers. A
   projection may be cached and rebuilt; it cannot grant, reset, consume,
   reverse, or restrict anything.
7. **Risk Restriction Authority** owns explicitly authorized, scoped,
   evidence-backed restrictions with review and release paths. It is separate
   from admin identity, entitlement, funding, and data access.
8. **Communication Outbox** owns notification delivery state. Communications
   describe authoritative transitions but never cause or substitute for them.

### Invariants

- Customer available credit is never negative.
- Recurring credits never roll over.
- Every credit belongs to exactly one billing account owner, funding source,
  funded period or non-expiring purchase lot, and originating evidence record.
- Personal, organization, purchased, promotional, trial, internal, and
  Enterprise funding never merge into an unattributed balance.
- A read cannot create an account, organization, period, lot, ledger entry,
  entitlement, reset, restriction, or schedule.
- Authentication cannot allocate, reset, or synchronize billing state.
- Organization resolution cannot select a funding owner by active context.
- Every AI charge is bound to one operation and one reservation/settlement
  chain; unusable or unpersisted results settle zero or receive an exact
  compensating release.
- Expiring eligible value is consumed first. Purchased value is protected
  behind expiring value. Within the same expiry, deterministic source priority,
  funded-at time, and lot ID break ties.
- Recurring lots expire at their period end even while held for a dispute.
- A refund, dispute, or recovery affects only attributable funding sources.
- Recovery cannot create purchasing power above the original entitlement.
- Saved work is never deleted or reassigned by billing transitions.
- Capabilities, data access, admin authority, and funding are independent.
- Stripe event arrival order never overrides effective-time and cumulative-
  amount rules.

### Approved business semantics

- Annual subscriptions are paid annually but receive monthly anchored funded
  periods. The anchor is the paid subscription's UTC billing anchor; month-end
  anchors clamp to the last UTC calendar day. The annual payment funds those
  periods, but no future monthly lot becomes spendable before its period opens.
- Free receives 300 credits per month from the immutable account-creation UTC
  anchor, with no rollover.
- A Free-to-paid successful payment starts a new full paid period. A paid
  upgrade keeps the existing anchor and grants only the deterministic,
  integer-floored UTC proration after payment succeeds.
- During Stripe dunning, funded credits and capabilities remain valid through
  their effective periods; no unfunded lot is issued. Terminal failure follows
  the approved terminal policy.
- One-time partial refunds reverse the purchase-specific unused portion in the
  same proportion as cumulative principal refunded, excluding taxes and fees.
  Bonus-package credits follow the same proportional rule.
- Subscription refunds record a reviewed disposition: financial-only or an
  entitlement-reducing action. Money movement alone cannot silently change
  capabilities or credits.
- Trials and comps require approved offers. Internal accounts require explicit
  internal funding, not plan impersonation.
- A monthly downgrade activates only after the next monthly renewal succeeds;
  an annual downgrade activates only after the annual renewal succeeds. A
  failed renewal grants neither the lower tier nor new credits. Later success
  activates the lower tier without moving the anchor.
- Exactly one active scheduled plan change exists per subscription. A confirmed
  compatible change may supersede it; a successfully paid immediate upgrade
  supersedes a pending downgrade; cancellation takes precedence; browsing is a
  no-op; all prior schedule records remain auditable.
- Seat occupancy and paid commitment are separate. A reduction is blocked when
  occupancy exceeds the target. It never removes members or work.
- Disputes have `opened`, `pending`, `won`, and `lost` states. Open/pending place
  source-specific holds on unused attributable credits. Won releases the exact
  hold. Lost reverses it; consumed shortfall is absorbed by Jaspen. Unrelated
  funding and future renewals continue unless an authorized risk restriction
  says otherwise.
- Mixed invoices are attributed by line. Subscription dispute attribution is
  proportional to subscription principal only and excludes taxes, fees, and
  unrelated lines.

### Consequences

Positive consequences:

- balance reconstruction and reconciliation are deterministic;
- no hidden dual writer is needed after cutover;
- reads are safe and cacheable;
- refunds and disputes become cumulative and source-specific;
- scheduled changes and seats have auditable precedence;
- Enterprise and internal funding stop masquerading as consumer plans;
- compatibility fields can be retired on measurable conditions.

Costs and constraints:

- Phase 2 requires additive schema and a controlled dual-read/verify period;
- current direct writers must be frozen and retired, not wrapped indefinitely;
- legacy balances need evidence-ranked attribution and explicit
  `legacy_unattributed` opening lots where attribution is impossible;
- financial reconciliation and credit reconciliation must both pass before a
  write cutover;
- exact customer communication wording requires separate review.

### Rejected alternatives

- **Patch each reset path.** Rejected because it leaves multiple authorities
  and cannot prove balance conservation.
- **Use Stripe as the application database.** Rejected because Stripe does not
  own AI operations, internal funding, credit consumption, Enterprise
  contracts, or customer data access.
- **Keep mutable balances plus an audit log.** Rejected because the counter and
  log can diverge and neither is unambiguously authoritative.
- **One table for money, entitlements, and credits.** Rejected because those
  facts have different lifecycles, owners, and reversal semantics.
- **Permanent compatibility synchronization.** Rejected because it creates
  hidden dual writers. Compatibility projections must be read-only and sunset.

## D05 Target service-boundary diagram

```text
 Stripe / contracts / approved offers / authorized admins
                  |
                  v
        +----------------------+       +----------------------+
        | External Event Inbox |------>| Billing Account     |
        | dedupe + ordering    |       | explicit payer/owner |
        +----------+-----------+       +----------+-----------+
                   |                              |
                   v                              v
        +----------------------+       +----------------------+
        | Financial Authority |------>| Entitlement Authority|
        | invoices/lines/money |       | plans/contracts/seats|
        +----------+-----------+       +----------+-----------+
                                                  |
                                                  v
 +----------------------+              +----------------------+
 | AI Operation        | reserve/settle| Credit Ledger        |
 | Authority           +------------->| lots + append entries|
 | validate usable work|<-------------+ balance by projection|
 +----------+-----------+              +----------+-----------+
            |                                         |
            +-------------------+---------------------+
                                v
                    +-------------------------+
                    | Pure Projection Layer   |
                    | billing/access/usage UI |
                    +------------+------------+
                                 |
                +----------------+----------------+
                v                                 v
      Authentication & APIs              Communication Outbox
      read only; no allocation           audited, idempotent,
                                         non-authoritative

 Risk Restriction Authority is an independent scoped gate consulted by
 capability and operation authorization. It does not rewrite any box above.
```

### Command ownership

| Command family | Sole target owner | Required evidence |
|---|---|---|
| Record invoice/payment/refund/dispute/recovery | Financial Authority | processor event/object and line attribution |
| Grant/revoke/schedule plan or contract capability | Entitlement Authority | successful payment, approved offer, executed contract, or approved disposition |
| Open/expire/hold/reserve/settle/release/reverse/recover credits | Credit Ledger | authoritative financial/entitlement/operation reference |
| Schedule/cancel/supersede plan change | Entitlement Authority | authenticated command plus processor confirmation when applicable |
| Change seat commitment | Entitlement Authority | authorized org admin command and occupancy check |
| Restrict account risk | Risk Restriction Authority | authorized Jaspen admin, evidence, scope, justification, and review metadata |
| Notify customer/admin | Communication Outbox | committed domain event |

## D03 Authoritative-vs-derived field dictionary

The names below are conceptual target fields. Phase 2 may choose physical names
only after this ADR is reviewed.

### Authoritative target fields

| Entity | Field | Meaning |
|---|---|---|
| Billing account | `id`, `owner_type`, `owner_id` | Explicit personal or organization payer; immutable ownership except audited transfer |
| Billing account | `processor_customer_id`, `currency`, `status` | Processor identity and account lifecycle, not capabilities |
| Financial transaction | `kind`, `external_reference`, `effective_at`, `currency` | Immutable invoice/payment/refund/dispute/recovery fact |
| Financial line | `source_type`, `source_id`, `principal`, `tax`, `fee`, `discount` | Exact mixed-invoice attribution in minor currency units |
| Entitlement definition | `key`, `capability_set`, `funding_policy` | Versioned approved commercial definition |
| Entitlement instance | `billing_account_id`, `definition_key`, `state`, `starts_at`, `ends_at` | Effective capability grant; separate from money and balance |
| Contract | `organization_id`, `executed_reference`, `effective_interval`, `terms_version` | Enterprise authority; never inferred from plan text |
| Credit period | `billing_account_id`, `anchor_at`, `starts_at`, `ends_at`, `status` | One funded recurring interval |
| Credit lot | `owner`, `source_type`, `source_id`, `original_amount`, `available_at`, `expires_at` | Funding-specific, immutable origin and limit |
| Ledger entry | `lot_id`, `entry_type`, `amount`, `effective_at`, `idempotency_key` | Append-only signed movement; correction uses another entry |
| Ledger entry | `operation_id`, `financial_line_id`, `related_entry_id`, `metadata` | Traceability, never mutable balance state |
| AI operation | `id`, `idempotency_key`, `request_fingerprint`, `state` | Exactly-one operation lifecycle |
| AI operation | `reservation_entry_id`, `settlement_entry_id`, `usable_result_reference` | Binding from result to credit entries |
| Scheduled change | `subscription_id`, `kind`, `target`, `effective_rule`, `state`, `precedence` | One active plan change with retained history |
| Seat commitment | `organization_id`, `quantity`, `interval`, `effective_interval`, `state` | Paid commitment, independent of occupancy |
| Risk restriction | `scope`, `evidence`, `justification`, `actor`, `effective_at`, `review_at`, `release_path` | Explicit, proportionate permissioned restriction |
| External event | `provider`, `event_id`, `object_id`, `object_version/effective_at`, `payload_digest`, `state` | Inbox identity and ordering evidence |
| Outbox message | `domain_event_id`, `template_key`, `recipient`, `dedupe_key`, `delivery_state` | Non-authoritative communication delivery |

### Derived target fields

| Projection field | Derivation | Current compatibility name(s) |
|---|---|---|
| `available_credits` | Eligible grants + releases/recoveries − settlements/holds/reversals/expirations | `User.credits_remaining`, status `credits_remaining` |
| `period_remaining` | Available entries restricted to one funded period | `ui_preferences.thinking_power.remaining`, `organizations.settings.thinking_power.remaining` |
| `credits_used` | Settled usage for period; never `limit - combined balance` | status `credits_used`, `tokens_used_this_month` |
| `next_allocation_at` | Next period boundary from immutable anchor | `credits_reset_at`, `cycle_reset_at` |
| `effective_plan_key` | Active entitlement definitions after time and scoped risk checks | `effective_plan_key()` result |
| `subscription_status` | Financial/subscription state projection | `User.subscription_status` |
| `scheduled_plan_change` | Active scheduled-change record by precedence | Stripe metadata `scheduled_plan_change` |
| `seat_occupancy` | Active memberships by role | `build_seat_usage()` output |
| `seat_commitment` | Effective seat commitment record | `Organization.max_total_paid_seats` |
| `has_offer` | Active entitlement instance | `AccountEntitlement`, `has_300k_limited_time` |
| `persistent_credits` | Available non-expiring lots by owner/source | sum of `PersistentCreditGrant.remaining_amount` |
| `billing_interval` | Effective subscription/contract terms | live Stripe price/metadata |
| `access_restricted` | Scoped capability decision with reason | status Boolean |

### Current fields that must not remain authoritative

| Current field | Current problem | Target disposition |
|---|---|---|
| `User.credits_remaining` | Combined mutable counter written by unrelated paths | Read-only compatibility projection; remove after consumers migrate |
| `User.credits_reset_at` | First-read/current-time drift; mixed period marker | Project `next_allocation_at`; never write from reads |
| `User.ui_preferences.thinking_power` | Billing authority hidden in UI JSON | Rebuildable projection only, then retire |
| `Organization.settings.thinking_power` | Organization ledger hidden in settings JSON | Rebuildable projection only, then retire |
| `PersistentCreditGrant.remaining_amount` | Mutable lot counter alongside transaction log | Derive from append-only ledger; freeze then retire as authority |
| `User.subscription_plan` | Mixes desired plan, paid entitlement, internal privilege | Compatibility projection of entitlement only |
| `User.subscription_status` | Stripe-like state used directly as access policy | Financial projection; entitlement policy reads explicit periods |
| `User.stripe_*` | Payer relationship tied to a person | Move authority to billing account; retain aliases temporarily |
| `Organization.plan_key` | Synchronized on reads from owner user | Pure entitlement projection, never resolver-written |
| `Organization.max_total_paid_seats` | Commitment and policy override are conflated | Project effective seat commitment |
| `StripeWebhookEvent.processed` | Receipt Boolean lacks object ordering and result | Retain as legacy receipt; new inbox owns processing state |
| `Payment` | Positive receipts only, no line/refund/dispute lifecycle | Backfill into financial transactions/lines; keep immutable archive |
| `UsageEvent.credits_charged` | Telemetry can be mistaken for balance authority | Analytics-only projection linked to ledger settlement |
| `AIOperation.charged_credits` | Operation audit duplicates settlement amount | Derive/check against linked ledger entry |

### Projection rule

During migration, compatibility fields may be populated only by a projector
from committed target events. No legacy endpoint may write through those fields
back into an authority. Sunset requires 30 consecutive days with zero legacy
writes, zero reconciliation drift, and all named consumers moved; the duration
is an engineering observation window, not a customer policy deadline.
