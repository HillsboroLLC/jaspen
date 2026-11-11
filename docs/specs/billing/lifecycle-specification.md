# Billing Lifecycle Specification

This specification defines target behavior only. State transitions are commands
executed in one database transaction unless an explicit external confirmation
boundary is named.

## D06 Credit-lot and ledger-state specification

### Funding ownership

Every lot is owned by one explicit organization billing account. Every
customer, including a single person, belongs to an organization; `personal`
and `organization` are not competing billing-owner types.

A lot may carry `member_attribution_id` and an eligibility scope when approved
commercial terms make value usable only by a named member. That preserves
source ownership and prevents teammate spending without inventing a second
billing system. Active organization selection never changes owner or
eligibility. An operation resolves its billing account from its durable
organization/work context before reservation, never from a UI picker alone.
Moving between organizations never transfers lots.

### Source taxonomy

| Source | Expiry | Required origin |
|---|---|---|
| `free_recurring` | funded-period end | account-creation anchored period |
| `subscription_recurring` | funded-period end | paid subscription line/period |
| `enterprise_recurring` | contract-defined period end | executed contract funding schedule |
| `credit_pack_purchase` | none unless approved offer says otherwise | paid one-time invoice line |
| `promotional` | approved offer terms | versioned approved offer |
| `trial` | approved offer terms | versioned approved trial offer |
| `comp` | approved offer terms | approved comp record and actor |
| `internal` | explicit terms | authorized internal funding command |
| `legacy_unattributed` | conservative evidence-backed expiry or none | migration reconciliation record |

`legacy_unattributed` is not a dumping ground. It is allowed only when source
and ownership are known enough to preserve value but historical evidence cannot
support a narrower source. The migration record stores candidates considered,
evidence, chosen owner, amount, expiry decision, reviewer, and reason.

### Lot fields and invariants

Each lot records owner, source, origin reference, original amount, available
time, optional expiry, funded-period reference, and immutable metadata. The
ledger, not a mutable `remaining` field, determines availability.

For lot `L` at time `t`:

```text
gross(L,t) = grants + releases + permitted recoveries
             - settlements - reversals - expirations
held(L,t)  = active dispute holds + active operation reservations
available(L,t) = max(0, min(original entitlement, gross(L,t)) - held(L,t))
```

The projection must reject, not clamp and hide, any invariant violation found
during writes. The displayed account balance is the sum of eligible lot
availability and therefore cannot be negative.

### Ledger entry types

| Entry | Signed effect | Rule |
|---|---:|---|
| `grant` | positive | one per funded lot/origin |
| `reservation` | hold | operation-bound; not consumption |
| `settlement` | negative | consumes reservation allocation for a delivered response's actual billable usage |
| `release` | removes hold | exact reservation/dispute allocation only |
| `expiration` | negative | unspent recurring value at period end; hold does not delay expiry |
| `refund_reversal` | negative | cumulative source-specific refundable unused value |
| `dispute_hold` | hold | unused attributable value only |
| `dispute_reversal` | negative | exact held value when lost |
| `recovery` | positive | restores prior reversed value, bounded by original entitlement |
| `admin_adjustment` | positive or negative | explicit authorized source and reason; never edits history |
| `migration_opening` | positive | evidence-backed opening lot only |

All entries require an idempotency key, actor or source event, effective time,
created time, lot, owner, and related entry/reference where applicable.

### Allocation order

For a reservation, eligible lots are sorted by:

1. earliest non-null `expires_at` (non-expiring last);
2. source protection priority: recurring/trial/promo/comp before purchased;
3. earliest `available_at`/funded time; and
4. stable lot ID.

The reservation persists its per-lot allocations. Settlement and release use
those allocations exactly; they never search for “recent usage” or infer a
source from an in-memory object.

### Operation reservation and settlement

```text
requested -> reserved -> provider_running -> delivered -> settled
                      \-> no_billable_usage ---------------------> released
                      \-> undelivered -> usage_recorded_as_absorbed -> released
```

AI usage billability rules were approved by the founder on 2026-11-11. Live
billing behavior is unchanged until the approved AI usage integration phase
(Phase 12), which implements and verifies them under separate authorization.

- Preflight is a pure availability query.
- Reserve is an explicit command with operation ID and maximum amount.
- A response is **delivered** when it has been shown to the customer or is
  durably saved where the customer can access it. Delivery, not response
  quality, determines billability.
- A delivered response settles the actual billable usage of the provider
  attempt that produced it, converted under the bound pricing-policy version,
  floored at zero and capped by the reservation unless an atomic supplemental
  reservation succeeds. Usage above that cap is recorded as Jaspen-absorbed,
  never silently dropped.
- Response quality, accuracy, usefulness, or customer satisfaction never
  determines billability.
- Unused reservation is released in the same transaction as settlement.
- If no provider-billable usage occurred, the exact reservation is released
  with no settlement.
- A provider attempt whose response is not delivered (provider error, timeout,
  output that cannot be delivered, or a Jaspen failure that leaves the response
  inaccessible) is not charged to the customer. Its known billable usage is
  recorded as Jaspen-absorbed with the evidence below.
- If a fallback provider then delivers a response, the customer is charged only
  for the delivering attempt's usage. The same provider usage is never charged
  twice.
- If the response was delivered or remains accessible, its usage is charged
  even if a later nonessential workflow step fails.
- A timeout or missing response is not assumed to have incurred provider
  charges. Available evidence is labeled reported, estimated, or unknown;
  uncertain usage is reconciled against provider records and never charged to
  the customer.
- Operation idempotent replay returns the prior result and makes no new entry.
- Authorization binds an immutable pricing-policy version. Provider retry,
  fallback, context expansion, and tool calls remain components of the same
  customer-visible operation.
- Capacity authorization is evaluated independently after a sufficient credit
  reservation and before chargeable provider execution. A capacity denial
  releases any newly created reservation atomically, records no settlement,
  returns `available_again_at`, and preserves the session at its last completed
  step.

### Absorbed provider usage evidence

Provider-billed usage that is not charged to the customer is retained with:
customer and operation identifiers; provider and model; the provider request
identifier where available; request and failure timestamps; provider-reported
token usage and cost where available, labeled reported, estimated, or unknown;
error category and delivery status; whether fallback was attempted and its
outcome; the Jaspen-absorbed amount and reason; and provider dispute or
investigation status and resolution. The record keeps enough evidence for
reconciliation and provider disputes without storing customer prompts or
responses.

### Customer billing disputes

A customer billing dispute follows an authorized investigation with documented
evidence and an audit trail. A resulting credit restoration is an
`admin_adjustment` entry with actor, reason, and evidence; a money refund
follows D10. Settlement logic never reverses a charge because of response
quality. Processor chargebacks are D10 disputes; provider-charge disputes are
tracked on the absorbed-usage evidence record.

## D07 Entitlement and credit-period state machines

### Entitlement instance

```text
proposed --(approved evidence)--> scheduled --(starts_at)--> active
active --(term ends)------------> expired
active --(approved disposition)-> reducing --(effective_at)-> expired/replaced
scheduled --(superseded/cancel)-> superseded/cancelled
```

Rules:

- Payment success, an approved offer, an executed contract, or an authorized
  internal grant is required to leave `proposed`.
- A trial, comp, or promotion is valid only when its separately approved,
  versioned offer completely defines eligibility, owner, capabilities, credit
  amount, start/end rules, funding source, and redemption limits.
- Financial dunning does not end an entitlement before its valid paid term.
- Subscription refund changes entitlement only through an explicit
  `financial_only` or `entitlement_reducing` disposition.
- Risk restrictions are evaluated separately and do not mutate the entitlement.
- Saved work and data access are not entitlement side effects.

### Recurring credit period

```text
planned --(funding confirmed and period opens)--> funded
funded  --(entries reserve/settle)--------------> funded
funded  --(ends_at)-----------------------------> expired
planned --(funding fails)-----------------------> unfunded
unfunded --(later success for same renewal)-----> funded
```

Rules:

- `planned` is not purchasing power.
- Funding creates one lot at most once for the period.
- No rollover: at `ends_at`, all unspent recurring value expires.
- A dispute hold does not extend the lot; expiration wins at the period end.
- A later payment success can fund an `unfunded` renewal period without moving
  the anchor, subject to the approved terminal policy and processor evidence.

### Anchors

- Free anchor: immutable organization account `created_at` in UTC.
- Monthly paid anchor: successful Free-to-paid activation in UTC; subsequent
  boundaries advance calendar months, clamping month-end day.
- Annual paid anchor: successful annual activation in UTC. Payment covers the
  annual term; funded credit periods open monthly on that anchor.
- Upgrade: retains the paid anchor.
- Downgrade after renewal success: retains the subscription anchor.
- Time arithmetic uses integer epoch/UTC values. No local-time rounding.

### Upgrade proration

For paid-to-paid upgrade after successful payment:

```text
remaining_seconds = max(0, period_end_utc - paid_at_utc)
period_seconds    = period_end_utc - period_start_utc
increment         = max(0, new_period_amount - old_period_amount)
prorated_grant    = floor(increment * remaining_seconds / period_seconds)
```

The grant is zero if the result is zero. It expires at the current period end.
For annual subscriptions, `old_period_amount` and `new_period_amount` are the
current monthly allocation amounts, not the annual sum. Free-to-paid does not
use this formula; it opens a new full paid period.

## D08 Upgrade, downgrade, and cancellation state machine

### Scheduled change states

```text
none -> pending -> awaiting_renewal_payment -> applied
              \-> superseded
              \-> cancelled
              \-> blocked_terminal_failure
```

One active scheduled change is allowed per subscription. Historical records
remain immutable.

### Command precedence

Highest precedence first:

1. confirmed cancellation;
2. successfully paid immediate upgrade;
3. explicitly confirmed compatible superseding schedule;
4. existing scheduled downgrade/change;
5. plan browsing (no command, no state change).

A cancellation supersedes an active scheduled downgrade. A successfully paid
immediate upgrade supersedes a pending downgrade. An attempted upgrade whose
payment fails changes neither entitlement nor credits and does not supersede
the pending schedule.

### Upgrade

| Current -> target | Payment result | Entitlement | Credits | Anchor |
|---|---|---|---|---|
| Free -> paid | success | target active immediately | full new paid-period lot | new paid anchor |
| paid -> higher paid | success | target active immediately | floored proration lot | unchanged |
| any upgrade | failed/pending | unchanged | no grant | unchanged |

Browser confirmation and webhook delivery share financial and allocation
idempotency keys. They may confirm the same successful payment, but can create
only one entitlement transition and one funded lot.

### Downgrade

- Monthly: effective at the next monthly renewal only after payment succeeds.
- Annual: effective at the next annual renewal only after payment succeeds.
- Before effective time, current capabilities and funded credits remain.
- On scheduled renewal failure, no lower-tier allocation is granted. Dunning
  preserves capabilities through the valid term but adds no unfunded credits.
- Later payment success applies the lower tier and funds the due period without
  moving the anchor.
- Terminal failure follows the approved terminal policy and preserves saved
  work; no policy is invented here.

### Cancellation

- `cancel_at_period_end` preserves capabilities and funded credits through the
  paid term.
- It supersedes pending plan changes.
- A resume command before period end cancels the cancellation and leaves the
  anchor unchanged.
- At term end, no renewal entitlement or credit lot is created absent payment.
- Cancellation never deletes members, projects, decisions, reports, or plans.

## D09 Seat-commitment state machine

Occupancy is the count of active members by governed role. Commitment is the
paid number of seats. They are different projections.

```text
current --(increase paid)----------------------> increased
current --(request reduction, occupancy <= n)-> scheduled_reduction
current --(request reduction, occupancy > n)--> blocked_occupancy
blocked_occupancy --(admin resolves)-----------> scheduled_reduction
scheduled_reduction --(renewal paid)-----------> reduced
scheduled_reduction --(payment fails)----------> awaiting_payment
scheduled_reduction --(cancel/supersede)-------> cancelled/superseded
```

Rules:

- Only an authorized organization billing admin can request a change.
- Reduction never removes or downgrades members and never deletes work.
- When occupancy exceeds target, commitment stays unchanged until the admin
  resolves occupancy or an authorized contract exception is recorded.
- Admins receive an event-driven notice ahead of the effective renewal. The
  notice event and delivery are audited and idempotent; this specification does
  not invent a lead time or wording.
- A failed renewal does not apply the lower commitment. Later success may apply
  it if occupancy is then compatible and the schedule remains active.
- Contract exceptions name scope, approver, evidence, effective interval, and
  review/release path.

## D10 Refund, dispute, and recovery state machine

### Cumulative case authority

One case per processor refund/dispute object and financial source tracks
cumulative principal, attributed lines, held credits, reversed credits,
released credits, recovered credits, and last accepted external version.
Repeated or out-of-order events recompute the desired cumulative effect and
append only the delta.

### One-time partial refund

For purchase line principal `P`, cumulative principal refunded `R`, and
purchase-specific unused-credit basis `U` (current unused value plus prior
refund reversals for that lot):

```text
ratio = min(1, max(0, R / P))
target_reversal = floor(U * ratio)
new_reversal = max(0, target_reversal - prior_refund_reversals)
actual_reversal = min(new_reversal, currently_unused_eligible_value)
```

Taxes and fees are excluded from `P` and `R`. A new bonus-package refund uses
the same proportional rule. Consumed shortfall is not made negative and is
recorded as absorbed when policy requires it.

### Subscription refund disposition

```text
refund_recorded -> financial_only
                -> entitlement_reducing_review -> scheduled/applied reduction
```

The disposition is mandatory and audited. Financial-only does not change
capabilities or funded credits. Entitlement-reducing names the affected period,
capabilities, and credit treatment and cannot delete saved work.

### Dispute

```text
opened -> pending -> won
                  -> lost
opened ----------> won/lost
```

- `opened`/`pending`: hold only unused credits attributable to disputed
  principal, by invoice line and source.
- `won`: release the exact still-live hold. Credits whose lots expired while
  held remain expired and are not recreated.
- `lost`: convert the exact still-live hold to reversal. Attributable value
  already consumed is Jaspen-absorbed shortfall, not a negative balance.
- `reopened` or processor correction is a new version of the same case and
  applies only the delta necessary to reach its cumulative state.
- Future renewals continue independently unless an authorized account-risk
  restriction explicitly says otherwise.
- No unrelated funding or account-wide capability is automatically suspended.

### Mixed invoice attribution

Financial lines classify subscription principal, seat principal, credit-pack
principal, other principal, discount, tax, and fee. A subscription dispute's
credit effect is:

1. exclude tax, fee, and unrelated lines;
2. allocate disputed principal across eligible subscription lines in
   proportion to their principal after line discount;
3. map each line to its funded periods/lots;
4. hold/reverse unused attributable value only.

### Recovery

- Recovery references prior reversal entries.
- It may restore at most the value previously reversed for the same source.
- If the original lot is expired, recovery cannot make it spendable beyond the
  original entitlement; policy may record financial recovery with zero credit.
- Total `grant + recovery - reversal` never exceeds original entitlement.

## D11 Account-risk permission and review model

Risk restriction is a separate authority, not a subscription status or admin
shortcut.

### Required record

| Field | Requirement |
|---|---|
| `scope` | named capability, funding source, operation class, billing account, or processor action; never implicit account-wide scope |
| `evidence` | durable references and evidence summary |
| `justification` | why the restriction is necessary and proportionate |
| `actor` | explicitly authorized Jaspen administrator identity and permission version |
| `effective_at` | explicit UTC instant |
| `review_at` | explicit UTC date chosen by authorized reviewer; no default deadline invented |
| `release_or_escalation_path` | named reviewer/action and customer-support path where applicable |
| `status` | proposed, active, under_review, released, escalated |
| `supersedes` | prior record when scope changes |

### Permissions

- Customer organization admins cannot create Jaspen account-risk restrictions.
- Global admin identity alone is insufficient; the actor needs the explicit
  risk-restriction permission.
- The actor cannot use risk authority to grant credits, change a contract,
  view customer data outside existing permissions, or delete saved work.
- Restrictions must be the narrowest effective scope.
- Urgent fraud/security restrictions may activate immediately but still
  require prompt authorized review. This ADR intentionally defines no numeric
  deadline or threshold.
- Release appends a release decision; it never erases evidence.

## D12 Communication event and outbox model

Authorities emit committed domain events such as:

- `payment_succeeded`, `payment_failed`, `dunning_started`, `dunning_resolved`;
- `credit_period_funded`, `credits_expiring`, `credits_expired`;
- `plan_change_scheduled`, `plan_change_superseded`, `plan_change_applied`;
- `seat_reduction_blocked`, `seat_change_approaching`, `seat_change_applied`;
- `refund_recorded`, `dispute_opened`, `dispute_won`, `dispute_lost`;
- `risk_restriction_applied/reviewed/released`.
- `low_credit_threshold_crossed`, `credits_exhausted`,
  `capacity_temporarily_restricted`, `capacity_restored`;
- `pricing_policy_change_announced` when customer credit consumption will
  change, including policy version, effective date, and impact class.

The same transaction inserts an outbox row with domain event ID, template key,
recipient account, locale, data references, and dedupe key. A worker delivers
and records attempt/result/provider IDs. Retry is safe by dedupe key. Delivery
failure cannot undo payment, entitlement, credits, or saved work.

Communications must be clear, timely, event-driven, idempotent, auditable, and
non-authoritative. Exact wording, channels, and timing thresholds are later
review items. The outbox stores references/minimal facts, not a shadow balance
or plan state.

The low-credit event is emitted at the configured 20% threshold at most once
per applicable recurring credit period. It states remaining credits, the next
refresh, and permitted purchase options. Customers do not configure custom
alerts in the initial release. Capacity messages are distinct from credit
exhaustion and disclose the next-available time without sensitive detection
rules. Delivery failure never changes the capacity, credit, or financial
decision.

## D13 Idempotency-key registry

| Command/event | Canonical key |
|---|---|
| External event receipt | `external:<provider>:<event_id>` |
| Financial object/version | `financial:<provider>:<object_id>:<version-or-cumulative-digest>` |
| Invoice/payment line | `line:<provider>:<invoice_id>:<line_id>:<fact_kind>` |
| Free period lot | `period:free:<billing_account_id>:<period_start_utc>` |
| Subscription period lot | `period:subscription:<subscription_id>:<period_start_utc>:<plan_version>` |
| Annual monthly allocation | `period:annual:<subscription_id>:<month_index>:<period_start_utc>` |
| Upgrade proration | `upgrade:<subscription_id>:<paid_invoice_line_id>:<effective_at>` |
| Approved offer lot | `offer:<offer_version>:<redemption_id>:<funding_component>` |
| Purchase lot | `purchase:<payment_line_id>:<package_component>` |
| Migration opening lot | `migration:<run_id>:<legacy_owner>:<source_key>` |
| AI operation | caller key plus request fingerprint; persisted unique |
| AI reservation | `reservation:<operation_id>:<attempt>` |
| AI settlement/release | `settlement:<operation_id>` / `release:<reservation_entry_id>:<reason>` |
| Refund delta | `refund:<refund_id>:<cumulative_principal>:<lot_id>` |
| Dispute state delta | `dispute:<dispute_id>:<state_version>:<lot_id>:<effect>` |
| Recovery | `recovery:<source_object_id>:<reversed_entry_id>:<cumulative_amount>` |
| Schedule command | `schedule:<subscription_id>:<client_command_id>` |
| Seat command | `seat:<organization_id>:<client_command_id>` |
| Risk decision | `risk:<restriction_id>:<decision_version>` |
| Outbox delivery | `message:<domain_event_id>:<template_version>:<recipient>:<channel>` |
| Pricing policy publication | `pricing:<policy_version>:<effective_at>` |
| Pricing change notice | `pricing-notice:<policy_version>:<billing_account_id>:<channel>` |
| Capacity authorization | `capacity:<policy_version>:<operation_id>:<window_key>` |

Keys are globally unique within their command namespace. Reuse with a different
fingerprint is a conflict, never a replay. Random UUIDs are not acceptable as
business idempotency keys when a stable external or operation identity exists.

## D14 External-event ordering rules

1. Verify signature, persist raw payload digest and event identity, then
   acknowledge only after durable inbox acceptance.
2. Duplicate event ID with the same digest is a replay. The same ID with a
   different digest is quarantined as an integrity conflict.
3. Business idempotency is based on object and cumulative state, not event ID;
   different event types for one purchase must converge.
4. Prefer provider object version or explicit effective time. Arrival time is
   only a last-resort tie-breaker and cannot move a state backward.
5. Fetching the current processor object is reconciliation evidence, not a
   reason to skip persisting the received event.
6. For cumulative amounts, recompute the desired total effect and append the
   delta from already-applied entries.
7. A stale subscription update cannot undo a later cancellation, paid upgrade,
   or terminal state. State-machine precedence applies before timestamps.
8. Invoice line attribution must finish before a credit-affecting refund or
   dispute command. Missing lines place the event in retryable review; no
   account-wide fallback is allowed.
9. A won dispute after lot expiry releases no expired purchasing power. A lost
   dispute after expiry records the case without double reversal.
10. Webhook and browser confirmation racing on the same payment use the same
    financial-object key and converge to one transaction, entitlement, lot,
    and communication event.
11. Processing failure records a retryable state and error. It never marks the
    event complete merely because the HTTP handler caught the exception.
12. Manual replay uses the same registry and produces no new effect unless
    authoritative cumulative state changed.

## D21 Pricing-policy lifecycle

Pricing is versioned separately from provider execution and from the ledger.
Each immutable pricing policy names:

- exact provider/model rate-table versions and units;
- customer-credit conversion and rounding rules;
- plan-budget and purchased-pack commercial versions;
- effective UTC instant and superseded version;
- whether the change affects customer credit consumption; and
- approval and notification evidence when customer impact exists.

```text
draft -> approved -> announced_if_required -> effective -> superseded
```

An operation binds the effective version before reserving credits and retains
it through retries, fallback, tools, validation, settlement, and replay. A new
version cannot reprice completed or in-progress operations. Rate ingestion may
be manual or automated in a future implementation, but publication is always
validated, approved, auditable, and fail-closed for an unknown billable model.
No Phase 1 document changes current prices, multipliers, plan allowances, or
pack economics.

## D22 Short-term capacity lifecycle

Capacity is a provider-independent authorization service, not a credit lot.
Its policy dimensions may include organization and member windows, operation
weight, permitted concurrency, entitlement tier, provider health, queue
priority, abuse signals, and safety restrictions. Numeric thresholds are not
approved in Phase 1.

```text
requested -> authorized -> running -> completed
         \-> delayed/denied_until -> eligible_for_retry
authorized -> expired_before_start
running -> interrupted -> resumable_from_last_completed_step
```

Rules:

- Evaluate organization-wide fairness as well as per-member monopolization.
- Higher tiers are eligible for more short-term capacity, concurrency, and
  preferential queueing, but no tier receives a promise beyond provider supply.
- Purchasing credits cannot bypass capacity or abuse restrictions.
- Claude-to-Gemini fallback reuses the same authorization and operation. Future
  OpenAI support uses the same interface and accounting contract.
- Provider 429/overload signals may reduce available service but do not alter
  customer credits or silently reset their capacity window.
- Runaway protection bounds provider attempts, tool iterations, context growth,
  operation duration, and total reserved exposure. Exhaustion yields a typed,
  resumable outcome rather than uncontrolled retries.
- Queue/retry responses include a safe `available_again_at` or retry interval;
  details of fraud/abuse scoring remain private.
- The policy version and authorization outcome are audit evidence, not ledger
  entries.

## D23 Usage & Billing projection and interruption behavior

The pure ledger/entitlement/financial projection supplies:

- tier, subscription status, and monthly/annual interval;
- available, used, recurring, and separately purchased credits;
- exact next credit refresh in UTC and customer-display time zone;
- next payment date and current subscription term;
- subscription management and permitted credit purchases;
- overall usage history and per-session credits/activity dates; and
- separate short-term capacity status and next-available time.

The account navigation label is **Usage & Billing**. UI copy may call capacity
`Usage`, units `Credits`, and the experience `Thinking Power`. The existing
top-right **BALANCE** indicator and hover behavior remain; no second persistent
meter is introduced.

Credit exhaustion blocks only new unfunded chargeable work. Capacity denial
blocks only temporarily unavailable work. Both preserve completed artifacts,
the decision session, the pending intent, and a durable checkpoint. When access
returns, the operation resumes from the last successfully completed step under
a new explicit authorization; it never repeats a settled step or charge. A step
interrupted before its response is delivered is not charged; its known provider
usage is recorded as Jaspen-absorbed.
