# Phases 2–5 Additive-Foundation Implementation Proposal

Status: **Phases 2.1–5.2 accepted and inactive; Phases 5.3–5.4 independently accepted and inactive, with integration into `develop` pending**

Founder architecture approval recorded: 2026-11-09

Scope: authoritative roadmap phases 2–5 only

## Accepted implementation status

This document remains the approved scope and historical authorization record.
Subsequent founder authorizations completed the following additive increments;
acceptance did not authorize backfill, runtime integration, activation, or
cutover.

| Increment | Status | Accepted migration / evidence |
|---|---|---|
| Phase 1 | Architecture reconciled and founder-approved | ADR-0001 and the Phase 1 deliverable package |
| Phase 2.1 | Implemented, independently verified, and accepted | `b5e7c9a1d3f2` |
| Phase 2.2 | Implemented, independently verified, and accepted | `c6f8d0b2e4a1` |
| Phase 2.3 | Implemented, independently verified, and accepted | `d7a9e1c3f5b2` |
| Phase 3 | Implemented, independently verified, and accepted | `e8b0f2d4a6c3`; accepted implementation commit `9969a1421e322d7840bde97c346c116425439dd0` |
| Phase 4 | Implemented, independently verified, merged into `develop` (`14cb0ab6`) with CI passing, and closed; not deployed or activated | `f9c1a3e5b7d4`; verified implementation commit `24c14d596973c311ba305d6e3132a7ed696074d7` |
| Phase 5.1 | Independently verified, accepted, and integrated; not connected or activated | `b2d4f6a8c0e3`; accepted baseline `26734e84eaa1f40d4344692f9126f72a56fa133e` |
| Phase 5.2 | Independently accepted and integrated into `develop`; inactive, not deployed or connected | `c3e5a7b9d1f4`; immutable financial transactions and source-attributed lines |
| Phase 5.3 | Independently accepted on PostgreSQL 18.6 (129 passed, 0 failed, 0 skipped); integration into `develop` pending; inactive, not connected or activated | `d3e5a7b9c1f4`; cumulative refund/dispute cases and immutable case evidence |
| Phase 5.4 | Independently accepted on PostgreSQL 18.6; integration into `develop` pending; inactive, not connected or activated | `e4b7c2d9a1f0`; immutable domain events, transactional communication outbox, and auditable delivery attempts |
| Phase 6 | Audit remediation and source-identity contract resolution implemented locally; independent re-review pending; inactive, not integrated, deployed, or activated | `f5c8d3e0b2a1`; immutable evidence binding free and paid subscription monthly periods to Phase 3 lots |

All accepted tables and links remain additive and inactive. Existing billing
continues to be authoritative until a separately approved migration,
reconciliation, and cutover sequence.

### Deferred hardening before Phase 5.1 inbox activation

| Area | Status | Required evidence |
|---|---|---|
| Phase 5.1/5.2 — Conflict evidence integrity | **Deferred — required before inbox activation** | `billing_inbox.record_event()` handles genuine concurrent duplicates idempotently, propagates unexpected `IntegrityError`s, and never leaves `digest_conflict` quarantine without durable conflict evidence. Required PostgreSQL regression cases: T-INBOX-01..03 in D17. |

## Original approval and authorization boundary

The founder approved ADR-0001, STOP-01 through STOP-25, the organization-first
model, and the 18-phase roadmap. As originally approved, this proposal did not
itself authorize application code, models, migrations, backfill, production
access, shadow traffic, cutover, legacy retirement, price changes, credit
changes, or numerical capacity rules. Phases 2.1–2.3 and 3 later received the
separate authorizations and acceptances recorded above. Every remaining phase
and implementation increment still requires separate approval.

The foundations are additive. During phases 2–5 the existing application keeps
reading and writing its legacy stores. New tables receive no customer data and
no dual writes until a later phase explicitly authorizes a command path. Empty
schema is not a competing authority.

## Mandatory safeguards in every acceptance review

Every phase-specific review must demonstrate, where applicable:

- one append-only credit ledger; no negative balance or unfunded AI use;
- idempotent funding, reservation, settlement, refund, and reversal identity;
- preservation of purchased credits, funded benefits, source attribution,
  sessions, completed work, and history;
- preservation of **Usage & Billing**, the existing **BALANCE** indicator, and
  one configurable 20% low-credit warning per applicable period; phases 2–5
  must not change or duplicate those surfaces;
- pure authentication, account, organization, and UI reads;
- an approved, authorization-time pricing version for chargeable AI work;
- charge only delivered responses, at actual billable usage and never twice;
  undelivered provider usage is Jaspen-absorbed with audit evidence, and
  response quality never determines billability;
- separate credit and short-term capacity decisions, with no unapproved limits;
- universal organization ownership and billing roles separate from membership;
- subscription-tier ownership of seat allowances/capabilities, with no plan or
  admin privilege inferred from a billing role;
- reuse of verified operation, provider-attempt, Redis, idempotency, and audit
  primitives where they satisfy the approved boundaries;
- retirement—not permanent synchronization—of competing authorities in later
  controlled phases;
- deterministic concurrency, event ordering, reconciliation, and rollback;
- no assertion of production configuration or realized margin without later,
  separately authorized evidence; and
- explicit proof that the change cannot activate customer-visible behavior.

### Safeguard-to-acceptance ownership

| Safeguard | Phases 2–5 acceptance evidence | Later enforcement gate |
|---|---|---|
| One append-only ledger; zero floor | Phase 3 entry immutability, account-lock trigger, concurrent overspend tests | Phase 12 AI integration; phase 17 cutover |
| No duplicate business effects | Phase 2 registry plus unique origin keys; phase 3–5 replay/race tests | Every later command cutover |
| Preserve purchased/funded/source value | No backfill or legacy writes; lots require exact org/source/evidence | Phases 13–17 reconciliation/backfill/cutover |
| Pure reads | No phase 2–5 runtime reader/writer; schema has no read-triggered defaults | Phase 13 inventory; phase 17 reader cutover |
| Approved authorization-time pricing | Phase 2 immutable policy/rate schema; phase 3 reservation FK | Phase 12 enforcement; phase 16 evidence |
| Preserve sessions/work; charge delivered responses only | No cascading FK from billing to work/session data; no execution integration | Phase 12 checkpoint/settlement tests |
| Credit exhaustion differs from capacity | Separate pricing/ledger and capacity policy identities; no limits seeded | Phase 12 service/UI behavior |
| Usage & Billing, BALANCE, 20% warning | Explicit no-change acceptance check for every phases 2–5 increment | Later projection/outbox/UI phase |
| Organization-first; tiers own seats/capabilities | Unique organization billing account and separate role grants; org-owned entitlements | Phases 7, 8, 11, 13–17 |
| Reuse verified controls | Preserve `AIOperation`/attempt and existing Redis paths; no duplicate replacement activated | Phase 12 coverage decision |
| Eliminate competing authorities | No permanent sync layer; nullable links only and written solely after later cutover authorization | Phases 13–18 |
| Reconciliation and rollback | Empty-table downgrade guard plus phase-specific rollback evidence | Phases 13–17 account/cutover reconciliation |
| No unapproved commercial/capacity policy | Empty policy catalogs; no seed/default activation | Separate founder/product approvals |

## Current dependencies that constrain the design

- IDs are generally UUID strings in `String(36)`; several audit/event tables
  use integer identities. The proposal follows that convention to avoid a
  repository-wide identifier migration.
- `Organization` and `OrganizationMember` exist. Billing identity still lives
  on `User`, and `active_organization_id` is navigation context.
- Legacy authority is distributed across `User`, organization/user JSON,
  `Payment`, `AccountEntitlement`, `PersistentCreditGrant`,
  `PersistentCreditTransaction`, `StripeWebhookEvent`, `UsageEvent`, and
  `AIOperation`.
- `AIOperation` already records organization, idempotency, provider attempts,
  policy version text, provider cost, projected/charged credits, and replay
  results. These fields are retained until later reconciliation proves a safe
  replacement/link.
- Alembic has a non-trivial historical revision graph. An implementation must
  run `alembic heads` against the authorized base and create a reviewed merge
  revision if necessary; this proposal does not guess a `down_revision`.
- PostgreSQL is the authoritative target for locking and triggers. SQLite test
  compatibility must be preserved with service-layer equivalents where a
  PostgreSQL trigger cannot execute.

## Phase 2 — Canonical additive schema

Phase 2 establishes identity and policy-version structures only. It does not
insert customer rows, move Stripe identifiers, or change a reader/writer.

### 2.1 `billing_accounts`

| Column | Proposed type / nullability | Rule |
|---|---|---|
| `id` | `String(36)` PK | application-generated UUID |
| `organization_id` | `String(36)` FK `organizations.id`, NOT NULL | `ON DELETE RESTRICT`; unique |
| `status` | `String(24)` NOT NULL | `proposed|active|restricted|closed`; default `proposed` |
| `currency` | `String(3)` NOT NULL | lowercase ISO currency; initial default is not seeded |
| `account_anchor_at` | timezone-aware UTC datetime NOT NULL | deterministic Free/account anniversary; never derived from a read |
| `processor` | `String(32)` NULL | e.g. `stripe`; not an entitlement |
| `processor_customer_id` | `String(255)` NULL | processor payer identity |
| `tax_context_json` | JSON NULL | non-authoritative processor/tax metadata |
| `created_at` | UTC datetime NOT NULL | immutable creation time |
| `updated_at` | UTC datetime NOT NULL | account metadata only, never balance |

Constraints and indexes:

- `UNIQUE (organization_id)` establishes one billing account per organization.
- Partial unique index on `(processor, processor_customer_id)` where customer ID
  is non-null.
- Checks for allowed `status`, three lowercase currency characters, and
  processor/customer both null or both populated.
- Index `(status, created_at)` for operational review.

There is no `user_id` owner and no dependency on `active_organization_id`.
Every future account-creation command must create the organization, membership,
billing account, and billing role explicitly in one transaction. Phase 2 does
not retrofit existing accounts; that belongs to phases 13–15.

### 2.2 `billing_role_grants`

| Column | Proposed type / nullability | Rule |
|---|---|---|
| `id` | `String(36)` PK | UUID |
| `billing_account_id` | FK `billing_accounts.id`, NOT NULL | `ON DELETE RESTRICT` |
| `user_id` | FK `users.id`, NOT NULL | `ON DELETE RESTRICT` |
| `role` | `String(32)` NOT NULL | `billing_owner|billing_admin|billing_viewer` |
| `state` | `String(16)` NOT NULL | `active|revoked|expired` |
| `starts_at` | UTC datetime NOT NULL | inclusive |
| `ends_at` | UTC datetime NULL | exclusive; null while open |
| `granted_by_user_id` | FK `users.id`, NULL | null only for explicit system/migration origin |
| `origin_type` / `origin_id` | `String(40)` / `String(255)`, NOT NULL | command, contract, or migration evidence |
| `created_at` | UTC datetime NOT NULL | immutable audit time |

Constraints/indexes: end after start; allowed role/state; unique
`(billing_account_id, user_id, role, starts_at)`; partial unique open grant on
`(billing_account_id, user_id, role)` where state is active and `ends_at` null;
indexes by account/state and user/state. A billing role never creates or implies
organization membership, plan entitlement, admin authority, or data access.

### 2.3 `idempotency_registry`

| Column | Proposed type / nullability | Rule |
|---|---|---|
| `id` | `String(36)` PK | UUID |
| `namespace` | `String(64)` NOT NULL | command/event family |
| `key` | `String(255)` NOT NULL | stable business identity |
| `request_fingerprint` | `String(64)` NOT NULL | SHA-256 canonical request digest |
| `state` | `String(24)` NOT NULL | `claimed|completed|failed_retryable|failed_final` |
| `result_type` / `result_id` | `String(64)` / `String(255)` NULL | durable result reference, not arbitrary response data |
| `claimed_at`, `completed_at` | UTC datetime | completed nullable |
| `last_error_code` | `String(120)` NULL | non-sensitive typed failure |

`UNIQUE(namespace, key)` is the claim boundary. Reuse with a different
fingerprint is a conflict. Claim uses `INSERT ... ON CONFLICT` followed by row
lock/read; random request UUIDs do not replace stable business keys.

### 2.4 Pricing-version foundation

`pricing_policy_versions`:

- `id String(36)` PK, `version String(64)` unique, `state String(20)` checked to
  `draft|approved|announced|effective|superseded`;
- `effective_at`, `approved_at`, `announced_at`, `superseded_at` UTC datetimes;
- `approved_by_user_id` nullable FK, `supersedes_id` nullable self-FK;
- `credit_conversion_version String(64)`, `rounding_rule String(32)`,
  `conversion_json JSON`, all immutable after approval;
- `customer_credit_impact Boolean`, `notice_required Boolean`, and
  `notice_evidence_reference String(255)`;
- check that an effective policy is approved, has an effective time, and has
  notice evidence when customer impact requires notice.

`provider_rate_entries`:

- UUID PK; pricing-policy FK; provider/model, currency, unit basis, input/output
  rates as `Numeric(20,10)`; optional cache/tool rate JSON; source reference and
  source observed time;
- `UNIQUE(pricing_policy_version_id, provider, model)`;
- nonnegative rates and supported unit-basis checks.

No pricing row is seeded and no current hard-coded rate is declared approved by
this schema change. Later Phase 12 must require one effective version and an
exact provider/model row before chargeable execution. This is the Phase 2
foundation for known findings 2 and 3, not their behavioral resolution.

### 2.5 Capacity-version foundation

`capacity_policy_versions` contains UUID/version, lifecycle state, effective
time, approval evidence, superseded version, and `rules_json`. It contains no
active row or numeric defaults in phases 2–5. Any future rules require a
separate approval. Phase 12 owns organization/member windows, concurrency,
tier priority, provider-pressure inputs, and abuse/runaway enforcement.

### 2.6 Nullable compatibility links

A later Phase 2 increment may add nullable, indexed FKs to existing tables:

- `ai_operations.billing_account_id`;
- `ai_operations.pricing_policy_version_id`;
- `ai_operations.capacity_policy_version_id`; and
- `payments.billing_account_id`.

They remain null and unread by current code. `AIOperation.policy_version` and
legacy organization/user references remain untouched. NOT NULL, uniqueness, or
reader changes require later reconciliation and cutover authorization.

### Phase 2 transaction and concurrency rules

- Organization/account/first-role creation is eventually one transaction, but
  no creation path is activated in this phase.
- Policy publication locks the superseded row, validates all rate entries and
  notice evidence, and changes at most one version to effective per instant.
- Partial unique indexes prevent duplicate active billing roles and processor
  identities.
- No current balance, entitlement, subscription, or Stripe row is locked or
  modified.

### Phase 2 tests and acceptance criteria

- Migration upgrade/downgrade on empty PostgreSQL and SQLite test databases.
- Existing application suite passes unchanged.
- Constraints reject user-owned accounts, duplicate organization accounts,
  duplicate processor identities, invalid role intervals, and idempotency-key
  fingerprint reuse.
- Pricing effective-state checks reject missing approval/notice evidence.
- No seeded pricing/capacity values and no application query references new
  tables.
- Schema inspection confirms no trigger/default creates rows during reads.
- Rollback rehearsal proves empty objects can be dropped in exact reverse order.

## Phase 3 — Credit ledger primitives

Phase 3 builds an unused ledger library and database invariants. It does not
backfill balances or connect current AI/billing writers.

### 3.1 `credit_lots`

UUID PK; `billing_account_id` NOT NULL/RESTRICT; `source_type` checked to
`free_recurring|subscription_recurring|enterprise_recurring|credit_pack_purchase|promotional|trial|comp|internal|legacy_unattributed`;
`source_id String(255)`; optional member-attribution user FK and
`eligibility_scope`; `original_amount BigInteger > 0`; `available_at` NOT NULL;
optional `expires_at`; optional future `credit_period_id` and financial-line
link; origin evidence JSON; created time. Unique
`(billing_account_id, source_type, source_id)` prevents duplicate funding.
Expiration must follow availability. The table has no mutable remaining amount.

### 3.2 `credit_reservations`

UUID PK; billing-account FK; `operation_id` FK to `ai_operations.id`, unique;
pricing-policy FK NOT NULL; capacity-policy FK nullable until Phase 12;
idempotency-registry FK unique; `requested_amount` and `authorized_amount`
positive; state checked to `reserved|partially_settled|settled|released|expired`;
request fingerprint; creation/expiry/finalization times. Reservation state is
coordination metadata; balance remains the ledger sum.

### 3.3 `credit_ledger_entries`

| Column | Rule |
|---|---|
| `id String(36)` | PK UUID |
| `billing_account_id`, `lot_id` | NOT NULL FKs, RESTRICT |
| `entry_type` | checked grant/reservation/settlement/release/expiration/refund/dispute/recovery/admin/migration taxonomy |
| `available_delta BigInteger` | signed available-balance movement |
| `held_delta BigInteger` | signed reservation/dispute-hold movement |
| `reservation_id` | nullable reservation FK |
| `operation_id` | nullable AI-operation FK |
| `related_entry_id` | nullable self-FK for release/reversal/recovery provenance |
| `idempotency_registry_id` | NOT NULL, unique FK |
| `effective_at`, `created_at` | UTC, NOT NULL |
| `actor_type`, `actor_id`, `reason_code`, `evidence_json` | mandatory provenance appropriate to entry type |

Checks encode transition shapes: a reservation/hold moves equal magnitude from
available to held; release reverses that shape; settlement/dispute loss reduces
held; expiration/refund reduces available; grant/recovery/migration increases
available. Neither delta may produce a no-op. Account IDs on lot, reservation,
operation, and entry must agree.

Reservation entries themselves are the durable per-lot allocation. Settlement
and release rows reference the reservation entry, so no transient ORM attribute
or mutable allocation counter is needed.

### Phase 3 concurrency and append-only enforcement

- A PostgreSQL `BEFORE INSERT` trigger locks the `billing_accounts` row
  (`FOR UPDATE`), verifies account/lot ownership, calculates committed available
  and held sums plus the proposed entry, and rejects either becoming negative.
- All lots are considered in expiry/source/time/ID order; transactions acquire
  account then lot locks in that stable order to avoid deadlocks.
- `UPDATE` and `DELETE` triggers reject changes to lots' origin fields and every
  ledger entry. Corrections append a new referenced entry.
- Service transactions claim idempotency, lock the account, insert reservation
  entries, and complete the registry atomically. A failure rolls back all.
- SQLite tests use the same service invariant and explicit serialization; they
  do not weaken the PostgreSQL production constraint.

### Phase 3 tests and acceptance criteria

- Grant/recover/reserve/settle/release/expire/reverse arithmetic and source
  attribution; correct earliest-expiry deterministic selection.
- Concurrent reservations cannot overspend and balances/holds never go below
  zero; deadlock retry retains one business result.
- Duplicate/fingerprint-conflicting keys, exact partial settlement/release,
  held-lot expiry, and correction provenance.
- Attempts to update/delete entries or mutate lot origin fail.
- Pricing version is mandatory for reservation; an unknown/unapproved version
  cannot be used.
- No legacy writer calls the library and all legacy balances remain byte-for-
  byte unchanged in tests.
- Downgrade is allowed only while all new tables are empty. Once entries exist,
  rollback means disabling unused new commands and preserving audit data.

## Phase 4 — Entitlement and credit-period foundations

Phase 4 creates inactive definitions and state-machine primitives. It does not
grant a plan, allocate a lot, or change access checks.

### Proposed tables

`entitlement_definitions`: UUID PK; stable `key`; integer `version`;
capability/funding-policy JSON; effective/retired times; approval evidence;
`UNIQUE(key, version)`; immutable after approval.

`billing_subscriptions`: UUID PK; billing-account FK; processor and external
subscription ID; interval checked `month|year|custom`; immutable UTC anchor;
term start/end; state; current entitlement-definition FK; external evidence;
unique processor subscription identity. This is organization-owned and does
not move Stripe IDs during Phase 4.

`entitlement_instances`: UUID PK; billing-account and definition FKs; optional
subscription FK; state checked to
`proposed|scheduled|active|reducing|expired|superseded|cancelled`; starts/ends;
source type/id and approval evidence; superseded-instance self-FK. End follows
start; origin tuple is unique. State changes lock account/subscription and append
an audit event; overlapping incompatible active definitions are rejected.

`credit_periods`: UUID PK; billing-account FK; entitlement-instance and
subscription FKs nullable as appropriate; kind checked
`free|monthly_subscription|annual_monthly|enterprise`; immutable `anchor_at`,
start/end, planned allocation amount, state
`planned|funded|unfunded|expired`; funding idempotency FK; funded-lot FK nullable;
`UNIQUE(billing_account_id, kind, starts_at)` and end-after-start check.

`entitlement_events`: append-only UUID rows containing instance, transition,
from/to state, effective/created time, actor/source, idempotency registry, and
evidence. Unique idempotency reference.

### Phase 4 transaction and timing rules

- Calendar boundaries are generated from immutable UTC anchors, including
  month-end clamp and leap-year behavior; reads never create periods.
- Period creation and funding are separate commands. `planned` is not credit.
- Funding locks account, period, and financial evidence, inserts one lot and
  grant entry, then marks the period funded in one transaction.
- Annual subscriptions create/open one monthly period at a time; no annual
  full-credit grant exists.
- Failed funding marks/retains an unfunded period without removing earlier
  benefits. No current entitlement gate is changed in Phase 4.

### Phase 4 tests and acceptance criteria

- Universal organization ownership; active UI organization cannot select an
  entitlement or period.
- Free/monthly/annual anchors, month-end/leap-year calculations, late login,
  no rollover, and one annual monthly period at a time.
- Duplicate funding/webhook/browser confirmation converges to one lot.
- Funding failure preserves existing funded lots and entitlement interval.
- Definitions/instances cannot imply admin authority or unlimited Enterprise
  value; contract-specific implementation remains Phase 11.
- No current plan/status/access reader uses the new tables.
- Empty-schema downgrade is reversible; funded rows make destructive downgrade
  prohibited.

### Phase 4 implementation record

Phase 4 was authorized as one inactive, cohesive foundation under the standing
whole-system architecture standard. The following vocabulary and ownership
rules are part of that authorization:

- Subscription lifecycle states are `proposed`, `incomplete`, `active`,
  `past_due`, `unpaid`, `paused`, `cancel_at_period_end`, `cancelled`, and
  `expired`. This state describes processor/subscription coordination and never
  grants or removes effective capabilities.
- Entitlement-instance states remain `proposed`, `scheduled`, `active`,
  `reducing`, `expired`, `superseded`, and `cancelled`. Append-only
  `entitlement_events` are authoritative for transitions; instance state is the
  transactionally maintained current-state projection and cannot be edited
  independently.
- Credit-period states remain `planned`, `funded`, `unfunded`, and `expired`.
  Funding identity and the unique `funded_lot_id` result are write-once.
- Definitions use immutable `key`/`version` and `exclusivity_key` identities.
  Capability and funding payloads have explicit schema versions, explicit
  finite credit quantities, and no implicit unlimited benefits.
- Entitlement origins are `free`, `subscription`, `trial`, `promotion`,
  `comp`, `enterprise_contract`, or `internal`. Trial, promotion, comp, and
  contract activation remains blocked until their later authoritative phases
  supply the approved evidence; Phase 4 creates no substitute authority.
- `BillingAccount.account_anchor_at` is the Free-period anchor. Subscription
  anchors are immutable UTC values. One shared calendar policy owns month-end,
  leap-year, annual-monthly, and late-period calculations.
- `credit_periods.funded_lot_id` is the only period-to-lot relationship. The
  Phase 3 ledger remains the sole future credit authority.

Phase 4 has no live route, webhook, authentication, access-gate, background-job,
or UI integration. Disposable funding tests demonstrate only atomic compatibility
with the Phase 3 ledger; Phase 5 financial evidence and later command activation
remain mandatory before live funding.

Verification (2026-11-11): commit `24c14d5` passed independent verification
against a disposable PostgreSQL 18.6 database: Phase 4 concurrency tests across
six isolation combinations, Phase 3 ledger integrity, real migration-chain
upgrade/downgrade rehearsal with downgrade refused for populated tables,
independent probes, and the full PostgreSQL and SQLite suites. The founder
recorded Phase 4 as verified and implementation-complete, not deployed or
activated.

Runtime prerequisite: before any Phase 4 runtime activation, the production
backend must run Python 3.10 or later, with Python 3.12 preferred to match CI
and the Docker image. `app/billing_entitlements.py` uses `X | None` type
annotations that fail to import on Python 3.9. The Phase 4 models imported at
startup do not use that syntax, so the inactive foundation does not affect
current startup.

Existing legacy authorities remain intentionally unchanged during Phase 4:

| Legacy authority | Phase 4 disposition | Approved retirement |
|---|---|---|
| `User.subscription_plan` / `User.subscription_status` | Existing live compatibility authority | Inventory/backfill/cutover in phases 13–17; removal in phase 18 |
| `Organization.plan_key` synchronization | Existing live organization projection | Pure projection cutover in phase 17; removal in phase 18 |
| `AccountEntitlement` and founder-offer services | Existing live offer authority | Reconcile in phases 13–16; cut over in phase 17; retire in phase 18 |
| Persistent credit grants and transactions | Existing live legacy-credit path | Reconcile/backfill in phases 13–16; ledger cutover in phase 17; retire in phase 18 |
| Stripe billing routes and webhook writers | Existing live processor path | External inbox/financial foundations in phase 5; controlled writer cutover in phase 17 |
| Existing access and collaboration gates | Continue reading legacy state | Reader/projection cutover in phase 17; obsolete compatibility readers removed in phase 18 |

## Phase 5 — Financial transactions and external-event inbox

Phase 5 records no live processor events until separately authorized. It adds
the immutable structures and deterministic dispatcher contract.

### Proposed tables

`external_event_inbox`: UUID PK; provider/event ID; event/object type and object
ID; payload digest; minimally necessary payload JSON; provider-created and
received UTC times; processing state
`received|processing|processed|retryable|quarantined`; attempt count, next
attempt, processed time, error code; `UNIQUE(provider, event_id)`; indexes on
`(state,next_attempt_at)` and `(provider,object_id,provider_created_at)`. Same ID
with different digest quarantines.

`financial_transactions`: UUID PK; billing-account FK; kind checked invoice,
payment, refund, dispute, recovery, adjustment; provider/object identity;
external version or cumulative digest; effective time; currency; integer minor-
unit totals for principal/tax/fee/discount/gross; inbox-event FK; immutable
created time. Unique provider/object/kind/version identity and exact arithmetic
checks.

`financial_lines`: UUID PK; transaction FK; external line ID; line kind
subscription/seat/credit-pack/tax/fee/discount/other; source type/id; quantity;
currency and signed integer minor-unit principal/tax/fee/discount amounts;
optional subscription/entitlement link; unique transaction/external-line/kind.
`source_type` and `source_id` identify the external provider or catalog source;
they are not aliases for Jaspen subscription or entitlement IDs. The optional
subscription and entitlement foreign keys remain the authoritative internal
links. Consumers must validate those internal links and tenant ownership without
requiring `source_id` to equal either FK, restricting accepted evidence to
`stripe_price`, or rewriting historical accepted lines.

`financial_cases` and `financial_case_events`: case header uniquely identifies a
provider refund/dispute object and stores current cumulative state under row
lock; append-only events retain every accepted version, attributed lines,
cumulative principal, and resulting hold/reversal/release references. Detailed
credit effects activate only in Phase 9.

`domain_events` and `communication_outbox`: committed business-event identity,
minimal referenced facts, recipient/account, template/channel version, dedupe
key, delivery state and attempts. No delivery worker is activated. These tables
ensure later notification failure cannot roll back a financial transaction.

The approved increment boundary is Phase 5.3 for refund/dispute case
foundations and Phase 5.4 for domain events and the transactional outbox.
Phase 5.3 remains inactive and does not connect a live event source; its case
recorder commits case state, immutable case version, and exact source-line
attribution together. Phase 5.4 provides the separately callable domain-event
and outbox transaction primitive required before any delivery worker or event
integration; it has no live caller and does not itself commit, deliver, or
contact a provider.

### Phase 5 transaction and ordering rules

- Verify signature before acceptance; persist event ID/digest before dispatch.
- Claim inbox row with `FOR UPDATE SKIP LOCKED`; business idempotency uses
  object/version/cumulative state, not merely event ID.
- Financial header, lines, case event, domain event, and outbox row commit in one
  database transaction. External message delivery occurs after commit.
- Arrival time cannot move effective state backward. Missing line attribution
  is retryable/quarantined, never an account-wide guess.
- Browser confirmation and webhook share financial-object idempotency and
  converge. Phase 5 does not wire either caller.

### Phase 5 tests and acceptance criteria

- Duplicate, different-digest, cross-type, stale, out-of-order, concurrent, and
  replayed events converge deterministically.
- Exact minor-unit line arithmetic; taxes/fees/discounts cannot net invisibly;
  mixed invoices retain source attribution.
- Cumulative refund/dispute versions append only the delta; no credit effect is
  activated before Phase 9.
- Transaction rollback leaves no partial financial/domain/outbox record.
- Outbox retry/dedupe is independent of business success.
- No Stripe webhook or browser route references new services in Phase 5.
- Production/staging access and live payload replay remain prohibited.

### Phase 5.1 implementation record — minimal-data external event inbox

Status: **independently verified, accepted, and integrated; inactive.** Phase 5.1 was authorized on
2026-11-11 as the first Phase 5 increment. Migration `b2d4f6a8c0e3` adds
`external_event_inbox` and its append-only `external_event_inbox_conflicts`
evidence table; `app/billing_inbox.py` is an inactive library with no live
route, webhook, job, or reader. A later, separately authorized increment
verifies the Stripe signature at the webhook boundary and calls `record_event`.

**Data minimization.** The inbox keeps only what idempotency, reconciliation,
retries, and auditability require:

| Kept | Never kept |
|---|---|
| Provider, event ID and type, referenced object type and ID, livemode, provider-created and received times | Raw payload |
| SHA-256 digest of the exact verified request body | Payment-card details (number, last4, brand, expiry, fingerprint) |
| Processing state, attempt count (the claim token), retry time, lease expiry, processed time, bounded error code | Billing details, names, emails, addresses, phone numbers |
| Conflict evidence: each distinct conflicting digest, the event state when detected, and detection time | Metadata, descriptions, receipt emails, or any nested object |
| Allowlisted scalar summary: schema version, API version, status, currency, amounts, and Stripe IDs for customer, subscription, invoice, payment intent, charge, refund, dispute, checkout session | Any field not on the allowlist |

The database enforces the allowlist: the summary must be a flat object of
allowlisted keys with scalar values no longer than 255 characters. Event
identity, digest, summary, livemode, and timestamps are immutable after insert.

**Idempotency and conflict evidence.** `(provider, event_id)` is unique; a
repeated event with the same digest returns the existing row. A same-ID event
with a different digest is never stored as the event. Each distinct conflicting
digest is appended once to `external_event_inbox_conflicts`, whose rows cannot
be updated, deleted, or truncated, so historical conflict evidence is never
overwritten. An unprocessed event (received, processing, or retryable) is
quarantined as `digest_conflict`; a conflict that arrives while a worker holds
the event also fences that worker. Processed and already quarantined events
keep their state and gain the evidence row.

**Processing lifecycle and lease fencing.** `received -> processing ->
processed | retryable | quarantined`; `retryable -> processing | quarantined`;
`quarantined -> retryable` only by operator requeue after investigation. Claims
use `FOR UPDATE SKIP LOCKED` with a lease, and every claim adds exactly one
attempt. `attempt_count` is the claim token: completing, retrying, or
quarantining an event is a conditional update that must match the event, the
`processing` state, the worker's token, and an unexpired lease. A stale worker
(expired lease, reclaimed event, conflict quarantine, or already completed)
updates zero rows and receives `StaleClaimError`. The database independently
rejects worker transitions on an expired lease. Retries back off exponentially
from 60 seconds to a six-hour cap; after ten attempts an event is quarantined
as `retry_exhausted`.

**Retention policy.** The founder-approved initial retention period for
processed Stripe transport-inbox events is 400 days after processing, subject to
applicable legal and accounting requirements. It exceeds Stripe's 30-day
event-resend window and leaves more than a year for reconciliation and provider
disputes. Received, processing, retryable, quarantined, and conflicted events
are never deleted by retention. A database trigger rejects every other delete,
so neither a direct delete nor a purge with a future clock can shorten
retention. Automated purging is **inactive**: `purge_expired_events` is not
scheduled or called and may run only after separate authorization.

Inbox retention governs only this transport record. It does not set retention
for financial transactions, invoices, refunds, disputes, or their supporting
evidence. Those records (Phase 5.2 onward) follow their own accounting and legal
retention requirements, and their `RESTRICT` foreign keys to inbox events keep
referenced inbox evidence for as long as the financial record exists.

**Deployment requirement.** PostgreSQL triggers reject `TRUNCATE` of both inbox
tables. Because a table owner or superuser can still disable triggers or drop
the tables, the runtime application database role must not own these tables and
must not hold `TRUNCATE`, `TRIGGER`, or DDL privileges on them. Migrations run
under a separate owner role. This is a prerequisite for any future activation.

**Downgrade.** Downgrade is refused while either table has rows. On PostgreSQL
it first takes an `ACCESS EXCLUSIVE` lock on both tables, so a concurrent
receiver cannot commit an event between the emptiness check and the drop.

**Verification (2026-11-11).** On a disposable PostgreSQL 18.6 database and on
SQLite: the inbox suite (minimization against a full synthetic card payload,
database allowlist, idempotency, append-only conflict evidence including
conflicts during processing, lease fencing for expired and reclaimed claims,
retry exhaustion, retention, `TRUNCATE` rejection, the downgrade lock race, and
concurrent claims and receipt under READ COMMITTED, REPEATABLE READ, and
SERIALIZABLE), a direct-SQL probe of the real migration chain, Phase 3 and
Phase 4 integrity, and the full PostgreSQL and SQLite suites. Independent
acceptance passed and the increment was integrated into `develop` at
`26734e84eaa1f40d4344692f9126f72a56fa133e`. It remains inactive.

### Phase 5.2 implementation record — financial transactions and lines

Status: **independently accepted and integrated; inactive.** Migration
`c3e5a7b9d1f4`, directly after Phase 5.1 revision `b2d4f6a8c0e3`, adds empty
`financial_transactions` and `financial_lines` tables. The inactive
`app/billing_financial.py` recorder has no live route, webhook, browser
confirmation, worker, entitlement, or ledger caller.

The header records one immutable provider/internal business version using a
unique provider/object/kind/version identity, UTC effective time, lowercase
currency, and signed integer minor-unit principal, tax, fee, discount, and
gross components. Non-adjustment facts require a compatible, processed,
unconflicted Phase 5.1 inbox event for the same provider and object. Internal
adjustments retain an explicit Jaspen object identity/version without claiming
Stripe evidence.

Each immutable line retains its external identity, classification, source
type/id, positive quantity, currency, signed component amounts, and optional
subscription/entitlement provenance. Database constraints and ownership
triggers prevent cross-account or cross-currency evidence. PostgreSQL deferred
constraint triggers require at least one line and exact component-by-component
header reconciliation at commit; PostgreSQL also permits line insertion only
in the transaction that created its header, closing later append-only mutation.
The PostgreSQL creator marker is a full-width top-level transaction ID captured
at insert, so savepoints do not break header/line atomicity and `xmin` wraparound
cannot make an older header appear current. Separate deferred trigger wrappers
read the header and line row shapes without cross-referencing nonexistent
columns. The Phase 5.2 migration adds a reversible PostgreSQL conflict fence:
for processed events, a no-op update of the parent inbox row makes stale
snapshots retry instead of accepting unseen evidence. Unprocessed events are
fenced by their existing quarantine state update. The trigger does not update
processing rows, preserving Phase 5.1 state-transition rules and conflict
evidence. The inactive retention helper skips inbox events referenced by
financial transactions; `RESTRICT` preserves that evidence, and purging remains
unscheduled.
The shared recorder atomically enforces the same sealed line-set result for
SQLite. `RESTRICT` foreign keys preserve inbox and related evidence,
PostgreSQL rejects `TRUNCATE`, and downgrade takes an exclusive lock and refuses
to remove either populated table.

The recorder treats an identical business version and line set as a duplicate,
rejects reuse with different evidence, and permits out-of-order versions to be
recorded as distinct immutable facts without projecting a current state. This
increment deliberately creates no financial-case state, refund/dispute credit
effects, domain events, communication outbox, entitlement changes, or credit
ledger entries; those remain owned by separately authorized later increments.

### Phase 5.3 implementation record — refund and dispute cases

Status: **independently accepted on PostgreSQL 18.6; integration into `develop`
pending; inactive.** Acceptance completed with 129 passed, 0 failed, and 0
skipped. It did not authorize deployment, a live runtime caller, or billing
activation.
Migration `d3e5a7b9c1f4` follows Phase 5.2 and adds an empty case projection,
append-only case events, exact source-line attribution, and an append-only
reference table for later credit-ledger effects. `app/billing_financial_cases.py`
is not called by a route, webhook, worker, entitlement writer, or ledger
command. It consumes already-recorded Phase 5.1/5.2 evidence only.

The case identity is scoped to provider, case type/object, and source
financial transaction. The recorder serializes updates to an existing case,
uses provider financial-version identity for replay, rejects conflicting
version reuse, and ignores stale effective/received ordering without advancing
the projection. Accepted case state, immutable event, and source-line
attribution are written in one caller-owned transaction. PostgreSQL guards
reconcile cumulative principal to its attributed source lines at commit, seal
attribution to the event-creation transaction, validate inbox and financial
source ownership/currency, enforce state/disposition and transition rules, and
preserve immutable evidence. SQLite tests exercise the shared recorder
invariants and migration triggers.

This increment records case facts only: it does not calculate or apply credit
holds, releases, reversals, recoveries, refunds, or entitlement changes and
does not write credit-ledger entries. Exact line attribution must be resolved
before calling the recorder; missing or ambiguous attribution is rejected,
not inferred. Detailed credit effects remain Phase 9, and transactional domain
events/outbox remain Phase 5.4. The Phase 5.1/5.2 T-INBOX-01..03 hardening gate
is unchanged and remains required before inbox activation.

Each immutable case version retains its source financial-transaction and inbox
references, provider version, evidence fingerprint, state, disposition,
cumulative principal in integer minor units, and effective/received timestamps.
Its append-only line rows retain the exact integer minor-unit amount for each
referenced source financial line. The recorder enforces that line amounts sum
to the cumulative principal, equal the negated signed principal of the linked
Phase 5.2 refund/dispute transaction version, and do not exceed eligible
source-line principal. The linked transaction version is the authoritative
cumulative snapshot for that provider refund/dispute object; a correction or
reversal is a subsequent immutable transaction and case version, not a
reinterpretation of an earlier movement. Attribution capacity is enforced
across the current versions of distinct cases sharing a source line; superseded
historical versions remain immutable but do not consume current capacity. The
recorder never apportions or rewrites those values.

Each Phase 3 ledger entry may be linked to at most one immutable case version.
Multiple ledger entries may refer to one case version; a correction or reversal
must use its own new ledger entry rather than reusing an entry already owned by
another case version. This reference constraint does not create ledger effects
or make the case projection a second ledger authority.

**Phase 9 dependency and acceptance criteria:** the later credit-effect
implementation must consume or provide the exact line attribution before
recording a case version, apply D10's proportional refund/dispute rules using
integer minor-unit arithmetic, exclude taxes and fees, and preserve the
per-version source-line evidence recorded here. It must define and test a
deterministic residual/tie-break rule for proportional dispute allocations
before implementation. It must establish DB-verifiable source/lot provenance
atomically with each corresponding ledger-effect link, so a Phase 3 effect
cannot be attributed to an unrelated source line or lot. Its regression
coverage must include mixed invoices, discounted and ineligible lines,
cumulative partial-to-full changes, exact minor-unit boundaries,
replay/concurrency, and proof that unrelated funding and source lines are
untouched. No Phase 9 calculation or effect is activated by Phase 5.3.

### Phase 5.4 implementation record — domain events and transactional outbox

Status: **independently accepted on PostgreSQL 18.6; integration into `develop`
pending; inactive.** The complete Phase 5.1–5.4 PostgreSQL suite passed with
144 passed, 0 failed, and 0 skipped. The billing-foundation regression suite
passed with 62 passed, 0 failed, and 0 skipped. The PostgreSQL migration chain,
empty downgrade, and concurrency coverage under READ COMMITTED, REPEATABLE
READ, and SERIALIZABLE also passed.

Migration `e4b7c2d9a1f0` adds immutable, organization-account-scoped domain
events, deduplicated communication obligations, and append-only delivery-attempt
evidence. `app/billing_outbox.py` records the domain event and its outbox
obligations within a caller-owned transaction, claims concurrently with
PostgreSQL `FOR UPDATE SKIP LOCKED`, and records retry, delivery, and expired-
lease outcomes without committing or contacting a provider. Stable event keys,
request fingerprints, account-scoped foreign keys, and the canonical
`message:<event>:<template-version>:<account>:<channel>` key provide replay,
tenant-isolation, and duplicate-prevention boundaries. Reference JSON is
restricted at the database boundary to an array of unique, nonempty identifier
strings; it cannot become a financial, entitlement, or balance payload.

All five findings from independent review were remediated before acceptance:
the downgrade takes consistently ordered PostgreSQL exclusive locks before its
empty-table checks; direct, cascading, and combined `TRUNCATE` operations are
rejected for immutable Phase 5.4 evidence; concurrent-test sessions are closed
or rolled back before schema teardown; the Phase 5.1 importer guard recognizes
the new inactive library without allowing live callers; and the reference-only
JSON and canonical deduplication-key formats are database-enforced. Regression
coverage verifies atomic rollback, immutable evidence, idempotent replay,
tenant isolation, retry and lease recovery, concurrent claims, migration
upgrade/downgrade, and refusal to downgrade populated or concurrently populated
evidence tables.

Technical acceptance does not authorize integration, deployment, or
activation. There is no route, webhook, delivery worker, provider adapter, or
live runtime caller. Phase 5.1/5.2 inbox activation remains gated by
T-INBOX-01..03. Phase 9 remains responsible for refund/dispute credit effects,
and Phase 12 remains responsible for AI-operation integration; neither
dependency is implemented or activated by Phase 5.4.

### Phase 6 implementation record — free and subscription allocations

Status: **audit remediation and final source-identity contract resolution
implemented and locally verified on PostgreSQL 18.6; independent re-review
pending; inactive.** The implementation adds one immutable
`recurring_credit_allocations` evidence row for each funded free,
monthly-subscription, or annual monthly period. `app/billing_allocations.py`
locks the organization billing account before dependent rows, derives calendar
boundaries from the immutable account or subscription anchor, reads the credit
amount from the approved effective entitlement definition, and requires a
matching positive Phase 5.2 subscription payment line for paid allocations.
The caller owns the transaction; allocation, idempotency claim, Phase 4 period,
Phase 3 lot and grant entry, and immutable evidence commit or roll back
together. The caller must also supply at least one complete delivery obligation.
The same transaction records the canonical Phase 5.4 `credit_period_funded`
domain event and all obligations; expiration similarly records
`credits_expired` and its complete obligations before the period becomes
expired. Phase 5.4 validation, fingerprinting, event identity, message dedupe,
immutability, and replay-conflict behavior are reused without production
defaults for template, channel, locale, or timing.

Annual terms open only the current monthly period and never grant a full year
of value. Monthly renewals require payment evidence effective within that
monthly period. Free allocations use the organization billing-account creation
anchor and no financial line. Canonical D13 allocation keys, request
fingerprints, unique evidence links, account-scoped foreign keys, PostgreSQL
row locks, and migration triggers enforce replay, tenant, source, period,
definition, subscription-term, and payment-period contracts. Period expiration
removes unspent available and held value at the immutable end without rollover,
while retaining the Phase 3 source-entry provenance for every held allocation.

PostgreSQL 18.6 remediation verification completed with 263 Phase 2–6 tests
passing, with 0 failures and 0 skips. The complete empty-database migration
chain reached `f5c8d3e0b2a1`; empty downgrade to Phase 5.4 and re-upgrade passed;
populated/concurrent downgrade refusal, immutable evidence, direct-SQL D12
bypass rejection, fully migrated funding and expiration replay, atomic rollback,
concurrent allocation, concurrent expiration, and expiration versus held-value
changes under READ COMMITTED, REPEATABLE READ, and SERIALIZABLE passed. The
approved Phase 5.2 distinction is preserved: external provider/catalog
`source_type`/`source_id` evidence remains independent of the authoritative
internal subscription and entitlement foreign keys, with provider flexibility
and historical evidence compatibility. These results await the separately
assigned independent re-review.

Phase 6 has no route, webhook, scheduler, worker, provider call, live runtime
caller, legacy balance mutation, or billing activation. Phase 7 retains
upgrade/downgrade/proration and schedule ownership. Phase 9 retains purchase,
refund, and dispute credit effects. Phase 12 retains AI reservation and
settlement integration. Phase 5.4 immutable evidence and outbox guarantees are
unchanged.

## Backward compatibility and protection of current customers

1. All migrations are additive; existing columns, constraints, data, APIs, and
   response fields remain unchanged.
2. New FKs on existing tables are nullable. Financial case and ledger-reference
   tables start empty. The Phase 5.3 concurrency-only source-line fence table is
   intentionally backfilled for existing invoice/payment transactions and
   populated for subsequent eligible transactions by its migration trigger.
   That trigger only maintains coordination metadata; it creates no financial
   evidence, starts no billing workflow, and does not activate billing.
3. There are no dual writes in phases 2–5. Later command cutovers replace one
   writer at a time; compatibility fields become projections only after proof.
4. No session/work table is referenced with cascading deletion. Billing FKs use
   `RESTRICT` or `SET NULL` only where audit preservation permits it.
5. No legacy balance is copied or interpreted. Inventory/reconciliation is
   phase 13; backfill phase 14; rehearsal phase 15.
6. Current prices, allocations, multipliers, rate limits, and customer messages
   are untouched.

## Migration and rollback strategy

Each increment gets its own Alembic revision, models/tests, review, and approval.
Upgrade order is billing account → roles/registry/policy versions → ledger →
entitlements/periods → finance/inbox. Downgrade is reverse order.

Before any row exists, rollback drops only the newly introduced objects after
schema and application version compatibility checks. Every downgrade begins
with a row-count guard and fails rather than discarding evidence. After a ledger
entry, financial fact, or event has been recorded, destructive downgrade is no
longer valid: rollback disables new commands, retains additive tables, and
restores service from the last authorized legacy path. Append-only history is
never copied backward into mutable counters.

Every migration rehearsal must capture pre/post schema fingerprints, legacy row
counts/checksums, migration duration/locks, downgrade result, and an unchanged
legacy application smoke test. No customer-data rollback is part of phases 2–5
because no customer data is written.

## Sequencing and separate authorization gates

1. **Accepted:** Phase 2.1 empty `billing_accounts` and `billing_role_grants` schema.
2. **Accepted:** Phase 2.2 idempotency and pricing/capacity version catalogs.
3. **Accepted:** Phase 2.3 nullable compatibility links.
4. **Accepted:** Phase 3 unused credit-lot/reservation/ledger primitives and invariants.
5. **Closed (in `develop`, not deployed or activated):** Phase 4 inactive entitlement/subscription/period primitives (runtime activation requires Python 3.10+, 3.12 preferred).
6. **Accepted and integrated, inactive:** Phase 5.1 minimal-data external event inbox.
7. **Accepted and integrated, inactive:** Phase 5.2 immutable financial transactions and lines.
8. **Independently accepted, pending integration into `develop`, and inactive:** Phase 5.3 refund/dispute cases (PostgreSQL 18.6: 129 passed, 0 failed, 0 skipped; no live runtime caller or billing activation).
9. **Independently accepted, pending integration into `develop`, and inactive:** Phase 5.4 immutable domain events and transactional outbox (PostgreSQL 18.6; Phase 5.1–5.4: 144 passed, 0 failed, 0 skipped; billing foundations: 62 passed, 0 failed, 0 skipped; no live caller, worker, provider integration, or billing activation).
10. **Audit remediation and source-identity contract resolution implemented locally, pending independent re-review, and inactive:** Phase 6 free and subscription recurring allocations with atomic Phase 5.4 funding/expiration events and caller-supplied delivery obligations; external financial-line source identity remains separate from authoritative internal subscription/entitlement links (PostgreSQL 18.6 remediation verification: Phase 2–6 263 passed, 0 failed, 0 skipped; no live caller or billing activation).

No authorization should cover more than one numbered increment by implication.
Passing a schema migration does not authorize data creation or service wiring.

## Ownership of the five known findings

| Finding | Foundation in phases 2–5 | Behavioral owner / validation gate |
|---|---|---|
| Provider refusal/timeout classification | Preserve `AIOperation`/attempt evidence; no behavior change. | Phase 12 fixes the two failing tests before fallback is valid; phase 17 AI cutover blocked until green. |
| Legacy versus shadow pricing | Phase 2 pricing versions/rate rows and nullable operation link. | Phase 12 unifies authorization/conversion/settlement; Phase 16 validates production-like shadow evidence. |
| Unknown provider/model pricing | Unique explicit rate row per policy/provider/model; no wildcard approval. | Phase 12 fails closed before reservation/provider call; future provider adapters must pass T-PRICE parity. |
| Capacity governance | Phase 2 metadata-only capacity version; no limits. | Phase 12 implements organization/member fairness, concurrency, priority, provider pressure, abuse/runaway controls; Phase 16 simulation/observation. |
| Production economics | Schema retains policy/cost/attempt evidence. | Phase 16 or a separately authorized economics audit; no realized-margin claim before then. |

## Unresolved technical dependencies and risks

- The authorized implementation base and Alembic head graph must be resolved at
  execution time.
- Legacy organization coverage and payer mapping are unknown until phase 13;
  phases 2–5 must not assume every existing user already has one valid org.
- UTC-aware target columns must be tested against current naive-UTC Python code
  and SQLite fixtures without silently changing existing timestamps.
- PostgreSQL append-only/zero-floor triggers need privilege and performance
  review; every writer must use one lock order.
- Pricing conversion/rate values cannot be seeded merely by copying code
  defaults; approval/version/notice evidence is required.
- No numeric capacity rules exist; an empty capacity catalog is intentional.
- Processor objects may lack monotonic versions; the cumulative-digest fallback
  and reconciliation fetch rules require Stripe fixture review in Phase 5.
- Ledger and inbox growth require query-plan/load tests before any cutover.
- The two failing governance tests remain a Phase 12 blocker.

None of these risks requires a new founder business-policy decision for the
first empty-schema increment.

## Recommended first implementation step

The smallest independently reviewable and reversible step is **Phase 2.1:
create only the empty `billing_accounts` and `billing_role_grants` tables**.

It establishes organization-first identity and permission separation without
touching a user, organization, Stripe ID, balance, entitlement, route, or UI.
Acceptance requires empty upgrade/downgrade rehearsal, constraint tests, the
unchanged existing suite, and proof that no runtime code imports or writes the
tables.

Rollback: before any row creation, deploy the prior application version and run
the guarded downgrade to drop the two empty tables and their indexes/FKs. If a
row exists, the downgrade must stop and require review; it may not delete the
row. This step must receive explicit authorization before any implementation.

## Stop statement

No implementation has begun. No model, migration, application, test,
configuration, database, production/staging system, price, allowance, capacity
limit, deployment, cutover, or PR #27 state was changed. Work stops at this
proposal pending explicit authorization.
