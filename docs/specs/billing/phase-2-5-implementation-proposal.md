# Phases 2–5 Additive-Foundation Implementation Proposal

Status: **Planning proposal only; no implementation authorized**

Founder architecture approval recorded: 2026-11-09

Scope: authoritative roadmap phases 2–5 only

## Approval and authorization boundary

The founder approved ADR-0001, STOP-01 through STOP-25, the organization-first
model, and the 18-phase roadmap. This proposal does not authorize application
code, models, migrations, backfill, production access, shadow traffic, cutover,
legacy retirement, price changes, credit changes, or numerical capacity rules.
Each phase and each implementation increment below requires separate approval.

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
- no charge for failed, unusable, duplicated, or unpersisted work;
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
| Preserve sessions/work; charge usable persisted work only | No cascading FK from billing to work/session data; no execution integration | Phase 12 checkpoint/settlement tests |
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

`financial_cases` and `financial_case_events`: case header uniquely identifies a
provider refund/dispute object and stores current cumulative state under row
lock; append-only events retain every accepted version, attributed lines,
cumulative principal, and resulting hold/reversal/release references. Detailed
credit effects activate only in Phase 9.

`domain_events` and `communication_outbox`: committed business-event identity,
minimal referenced facts, recipient/account, template/channel version, dedupe
key, delivery state and attempts. No delivery worker is activated. These tables
ensure later notification failure cannot roll back a financial transaction.

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

## Backward compatibility and protection of current customers

1. All migrations are additive; existing columns, constraints, data, APIs, and
   response fields remain unchanged.
2. New FKs on existing tables are nullable. New tables start empty. No default,
   trigger, login, GET request, or organization resolver populates them.
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

1. **Phase 2.1 only:** empty `billing_accounts` and `billing_role_grants` schema.
2. Phase 2.2: idempotency and pricing/capacity version catalogs.
3. Phase 2.3: nullable compatibility links.
4. Phase 3: unused credit-lot/reservation/ledger primitives and invariants.
5. Phase 4: inactive entitlement/subscription/period primitives.
6. Phase 5: disconnected financial/inbox/case/domain/outbox primitives.

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
