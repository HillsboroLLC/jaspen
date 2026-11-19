# Billing Architecture Phase 1

Status: **Phases 1–5.2 accepted and integrated but inactive; Phases 5.3–5.4 independently accepted and inactive, with integration into `develop` pending**

Base: `origin/main` at `88684284a33836106cad639d36e191271109c2c7`

Prepared: 2026-11-09

Scope: architecture and traceability only

## Executive summary

Jaspen's current billing behavior is split across user columns, JSON meters on
users and organizations, persistent-credit grants, Stripe metadata, payment
rows, webhook receipt rows, AI-operation rows, and admin controls. Several
functions called by authentication and `GET /billing/status` also initialize,
reset, or synchronize balances. The same customer balance can therefore be
represented and changed in more than one place, while refunds, disputes,
dunning, scheduled changes, and seats do not have one cumulative lifecycle
owner.

The target architecture starts with one non-negotiable account rule: every
customer is an organization, whether it has one member or 1,500. Each has an
explicit organization billing account and separate billing-role permissions.
Active UI organization selection never chooses the payer or credit owner.

It replaces current overlap with deliberately separate authorities:

1. a financial transaction authority for money and Stripe evidence;
2. an entitlement authority for capabilities, plans, contracts, and seats;
3. one append-only credit ledger for every funded lot, hold, reservation,
   settlement, expiration, release, reversal, and recovery; and
4. an AI-operation authority that binds one delivered response's actual
   billable usage to one reservation and settlement without becoming a balance
   store; undelivered provider usage is Jaspen-absorbed with audit evidence.

Effective-dated pricing policy binds provider rates and customer-credit
conversion at operation authorization. A separate provider-independent
capacity policy governs short-term windows, concurrency, tier preference,
provider pressure, and abuse. Passing credits never implies passing capacity,
and a capacity denial never consumes credits.

Read models project those authorities. Authentication, billing status,
organization resolution, and AI preflight become pure reads. Stripe remains an
external payment processor and evidence source, not Jaspen's internal state
machine. Customer communications are emitted from an audited outbox and never
decide financial, entitlement, or credit state.

The replacement preserves customer money, funded credits, source/member
attribution inside organization-owned accounts, saved decisions and plans,
plan capabilities through valid paid periods, credit-pack value, promotional
value, audit evidence, and the regression intent of PR #27. It does not
preserve accidental reset-on-read, negative balances, rollover into a later term,
account-wide dispute penalties, direct balance edits, or duplicated
compatibility state as authorities.

Founder architecture approval was recorded on 2026-11-09 for ADR-0001,
STOP-01 through STOP-25, the organization-first model, and the authoritative
18-phase roadmap. Phases 2.1, 2.2, 2.3, and 3 were subsequently authorized,
implemented, independently verified, and accepted as additive, inactive
foundations. Phase 4 was then implemented and independently verified on
PostgreSQL 18.6 (commit `24c14d5`), merged into `develop` at `14cb0ab6` with CI
passing, and closed; it is not deployed or activated. Phase 5.1 (minimal-data
external event inbox) passed independent acceptance and was integrated into
`develop` at `26734e84eaa1f40d4344692f9126f72a56fa133e`. Phase 5.2's inactive,
immutable financial-transaction and source-attributed-line foundation was
independently accepted and integrated into `develop`. Phase 5.3's inactive
refund/dispute case foundation passed independent PostgreSQL 18.6 acceptance
(129 passed, 0 failed, 0 skipped); integration into `develop` remains pending.
Phase 5.4's inactive domain-event and transactional-outbox foundation also
passed independent PostgreSQL 18.6 acceptance (Phase 5.1–5.4: 144 passed, 0
failed, 0 skipped; billing foundations: 62 passed, 0 failed, 0 skipped). All
five independent-review findings were remediated: concurrent downgrade
protection, direct and cascading `TRUNCATE` protection, concurrency-test
cleanup, the inactive-library importer guard, and database enforcement of the
reference-only JSON and canonical deduplication-key contracts. Neither
increment has a live runtime caller or is connected to a webhook, browser
confirmation, delivery worker, provider integration, entitlement transition,
credit movement, or billing activation. Phase 6 is independently accepted at
checkpoint `ffe4ab0e09f4ca273748aabed6740017f7cc72f3`; its inactive allocation service binds configured free and
paid subscription entitlements to one monthly credit period and Phase 3 lot,
with immutable funding evidence and no recurring rollover. PostgreSQL 18.6
remediation verification completed with 263 Phase 2–6 tests passing, with no
failures or skips; fully migrated service paths, direct-SQL D12 bypass rejection,
concurrent expiration and held-value races, the complete migration chain, empty
Phase 6 downgrade, re-upgrade, and all three transaction-isolation variants passed.
The approved Phase 5.2 source-identity contract keeps external provider/catalog
`source_type` and `source_id` separate from the internal subscription and
entitlement foreign keys that authorize Phase 6 funding. Phase 6 neither equates
those identities nor restricts them to one provider convention. This is
implementation evidence, not independent acceptance or integration.
Phase 7 is implemented locally for independent review as an inactive plan-change
authority. It adds immutable one-active-schedule history, paid-upgrade proration,
Free-to-paid activation, renewal-gated monthly and annual downgrades,
period-end cancellation and pre-end resumption. Every change records its D12
domain event and caller-supplied delivery obligations in the caller-owned
transaction. PostgreSQL guards reject direct subscription-definition changes,
schedule evidence, and recurring proration lots that lack the matching Phase 7
authority. This implementation has no route, webhook, scheduler, worker,
provider call, live caller, deployment setting, or billing activation and is
not yet independently accepted or integrated.
The phases 2–5 proposal continues to
identify separately reviewable, reversible increments; no backfill, runtime
activation, or cutover is bundled. The stop-class conflicts in
[current-state-inventory.md](current-state-inventory.md#d20-newly-discovered-conflicts-and-stop-register)
remain later implementation work. The accepted work through Phase 3 has not
changed legacy billing behavior, customer data, deployment state, or PR #27.

## Package index and deliverables

| # | Deliverable | Location |
|---|---|---|
| D01 | Final ADR | [ADR-0001](ADR-0001-authoritative-billing-ledger.md) |
| D02 | Policy-to-component traceability | [traceability-and-cutover.md](traceability-and-cutover.md#d02-policy-to-component-traceability) |
| D03 | Authoritative-vs-derived field dictionary | [ADR-0001](ADR-0001-authoritative-billing-ledger.md#d03-authoritative-vs-derived-field-dictionary) |
| D04 | Current writer/reader/owner inventory | [current-state-inventory.md](current-state-inventory.md#d04-current-writer-reader-and-owner-inventory) |
| D05 | Target service-boundary diagram | [ADR-0001](ADR-0001-authoritative-billing-ledger.md#d05-target-service-boundary-diagram) |
| D06 | Credit-lot and ledger-state specification | [lifecycle-specification.md](lifecycle-specification.md#d06-credit-lot-and-ledger-state-specification) |
| D07 | Entitlement and credit-period state machines | [lifecycle-specification.md](lifecycle-specification.md#d07-entitlement-and-credit-period-state-machines) |
| D08 | Upgrade/downgrade/cancellation state machine | [lifecycle-specification.md](lifecycle-specification.md#d08-upgrade-downgrade-and-cancellation-state-machine) |
| D09 | Seat-commitment state machine | [lifecycle-specification.md](lifecycle-specification.md#d09-seat-commitment-state-machine) |
| D10 | Refund/dispute/recovery state machine | [lifecycle-specification.md](lifecycle-specification.md#d10-refund-dispute-and-recovery-state-machine) |
| D11 | Account-risk permission/review model | [lifecycle-specification.md](lifecycle-specification.md#d11-account-risk-permission-and-review-model) |
| D12 | Communication event/outbox model | [lifecycle-specification.md](lifecycle-specification.md#d12-communication-event-and-outbox-model) |
| D13 | Idempotency-key registry | [lifecycle-specification.md](lifecycle-specification.md#d13-idempotency-key-registry) |
| D14 | External-event ordering rules | [lifecycle-specification.md](lifecycle-specification.md#d14-external-event-ordering-rules) |
| D15 | Legacy retirement map | [current-state-inventory.md](current-state-inventory.md#d15-legacy-retirement-map) |
| D16 | Migration reconciliation specification | [traceability-and-cutover.md](traceability-and-cutover.md#d16-migration-reconciliation-specification) |
| D17 | Regression traceability matrix | [traceability-and-cutover.md](traceability-and-cutover.md#d17-regression-traceability-matrix) |
| D18 | Phase dependency/cutover map | [traceability-and-cutover.md](traceability-and-cutover.md#d18-phase-dependency-and-cutover-map) |
| D19 | PR #27 supersession analysis | [current-state-inventory.md](current-state-inventory.md#d19-pr-27-supersession-analysis) |
| D20 | Conflict/stop register | [current-state-inventory.md](current-state-inventory.md#d20-newly-discovered-conflicts-and-stop-register) |
| D21 | Pricing-policy lifecycle | [lifecycle-specification.md](lifecycle-specification.md#d21-pricing-policy-lifecycle) |
| D22 | Short-term capacity lifecycle | [lifecycle-specification.md](lifecycle-specification.md#d22-short-term-capacity-lifecycle) |
| D23 | Usage & Billing projection and interruption behavior | [lifecycle-specification.md](lifecycle-specification.md#d23-usage--billing-projection-and-interruption-behavior) |
| R01 | Architecture reconciliation report | [architecture-reconciliation-report.md](architecture-reconciliation-report.md) |
| R02 | Pricing and capacity verification report | [pricing-and-capacity-verification.md](pricing-and-capacity-verification.md) |
| P01 | Phases 2–5 additive-foundation implementation proposal | [phase-2-5-implementation-proposal.md](phase-2-5-implementation-proposal.md) |

## Acceptance assessment

The design assigns one target authority to every approved rule, maps approved
policies and lifecycle confirmations to components and tests, defines universal
organization ownership and deterministic precedence, and provides sunset
conditions for compatibility projections. The migration specification is
balance preserving and explicitly rejects silent data repair.

All 25 STOP items are founder-approved at the business-policy and architecture
levels. The accepted Phase 2 and Phase 3 foundations implement only their
approved additive schema, policy, compatibility-link, and inactive-ledger
boundaries. No claim is made that later phases or cutover are complete, that
production pricing is known, or that customer traffic uses the new ledger.

## Approved customer experience

- Navigation: **Usage & Billing**.
- Units: **Credits**; marketing language: **Thinking Power**.
- Retain the upper-right **BALANCE** indicator and hover; do not add a second
  persistent meter.
- Show available/used/recurring/purchased credits, usage/session history,
  subscription term and interval, next credit refresh, and next payment.
- Warn once per applicable credit period at a configurable 20% remaining.
- Explain capacity restriction separately from credit exhaustion, preserve the
  session, state when capacity returns, and charge nothing for an undelivered
  response (2026-11-11 delivery-based billability; lifecycle D06).

## Remaining decisions and evidence limits

The architectural boundaries are approved. Later approvals must select numeric
capacity/concurrency/priority thresholds
from authorized usage/provider evidence and approve notification wording,
channels, lead time, and any terminal dunning timing. Repository defaults are
not adopted as those policies. Production modes, rates/configuration, and
realized margin were not accessed or verified.

## Scope guardrails

- Phases 2.1–2.3 and Phase 3 are accepted. Phase 4 is closed: merged into
  `develop` at `14cb0ab6` with CI passing, not deployed or activated.
- Phase 5.1 is independently accepted and integrated at `26734e84`; the inbox
  remains disconnected from live Stripe webhooks and stores no card or
  unnecessary personal data (see the Phase 5.1 record in the proposal).
- Phase 5.2 is independently accepted and integrated into `develop`; its
  immutable money facts and source-attributed lines remain empty and inactive.
  Phase 5.3 passed independent PostgreSQL 18.6 acceptance (129 passed, 0 failed,
  0 skipped), but integration into `develop` remains pending. Its inactive
  refund/dispute case recorder has no live runtime caller and remains
  disconnected from live sources and billing activation.
- Phase 5.4 passed independent PostgreSQL 18.6 technical acceptance (Phase
  5.1–5.4: 144 passed, 0 failed, 0 skipped; billing foundations: 62 passed, 0
  failed, 0 skipped). Its immutable domain-event and transactional-outbox
  foundation remains inactive and pending integration into `develop`; there is
  no live caller, delivery worker, provider integration, or Phase 12 command
  path. Phase 9 credit effects and the Phase 5.1/5.2 inbox activation gate
  remain deferred under their approved contracts.
- Phase 6 is independently accepted at checkpoint
  `ffe4ab0e09f4ca273748aabed6740017f7cc72f3`. Free,
  monthly-subscription, and annual monthly allocations are additive and
  inactive. Each funding and expiration command requires caller-supplied,
  nonempty delivery obligations and atomically uses Phase 5.4 to record its
  domain event and outbox rows; no production template, channel, locale, or
  timing default is defined. The service has no route, webhook, scheduler,
  worker, provider call, or legacy billing caller. Phase 9
  refund/dispute and purchase effects, and Phase 12 AI-operation integration
  remain deferred. Financial-line `source_type` and `source_id` preserve external
  provider/catalog identity, while internal subscription and entitlement foreign
  keys remain authoritative for recurring funding; no historical financial line
  is rewritten or invalidated. Implementation and local verification do not authorize
  integration, deployment, or activation.
- Phase 7 scheduling, subscription-change, and proration behavior is implemented
  locally and pending independent acceptance. The additive migration records
  immutable schedule/event/proration evidence and extends the Phase 6 recurring
  guards only for separately evidenced upgrade proration. D08 precedence,
  failed-payment preservation, cancellation resumption, exact integer UTC
  proration, replay, rollback, tenant isolation, and concurrent commands are
  covered without introducing a live caller. Phase 9 purchase/refund/dispute
  credit effects and Phase 12 AI-operation integration remain deferred.
- Phase 8 seat commitments and occupancy are implemented locally and pending
  independent audit. The additive migration records immutable commitment
  intervals, D09 seat-change history, and a concurrency-only fence. Paid
  commitment stays separate from membership occupancy; reductions never remove
  members or work. Phase 11 adds contract-origin commitments; contract
  exceptions to the occupancy rule remain unapproved. There is no
  live caller.
- Phase 10 trials, promotions, comps, and internal funding are implemented
  locally; audit remediation (F1–F5, R2) is complete and pending independent
  verification. Recorded times come from the database transaction; grant
  expiry and offer retirement are judged at the actual current time; on
  PostgreSQL redemption and revocation require READ COMMITTED. Offers are approved, versioned
  entitlement definitions; comps and internal funding require an explicit staff
  permission grant, never admin identity or billing roles. The Phase 4
  later-authority gate now blocks only enterprise contracts (Phase 11); trial,
  promotion, comp, and internal entitlements need a Phase 10 redemption record.
  No offer or permission holder is defined, and there is no live caller.
- Phase 11 organization pools and Enterprise contracts are implemented locally
  for independent audit, inactive, on the Phase 10 checkpoint. Founder
  decisions of 2026-11-15: annual monthly releases accumulate and expire at the
  paid annual term end (monthly unchanged); credit packs expire at the end of
  the paid term in force at payment; Enterprise payment is verified through
  Stripe only; `billing.enterprise_contract.manage` is an explicit staff
  permission; each paid contract term is a contract-backed subscription that
  reuses Phases 4, 6, and 8. Renewal grace (15 days, read-only) and the
  180-day retention-review date are recorded, not enforced; nothing is
  deleted. See the Phase 11 record in the traceability document.
- Phase 12 AI reservations, capacity authorization, and delivery-based
  settlement are accepted (local checkpoint `4efabb05`, not pushed), inactive,
  on the accepted Phase 11 checkpoint. An operation binds the effective pricing and
  capacity versions; unknown economics fail closed; only a delivered
  response's provider-reported usage is charged, and everything else is
  recorded as Jaspen-absorbed. Audit findings F1–F8 were remediated on
  2026-11-16 under that day's founder decisions: a renewable reservation lease
  keeps a delivered response billable after the original deadline, and every
  member has an individual fair-use allowance inside their organization. The
  founder decisions of 2026-11-17 keep a response whose lease lapsed: it is
  recorded as delivered and never charged. Token allowances count only
  verified, delivered usage. Activation is gated on the Phase 17
  reliable-delivery integration. No rate,
  conversion, or capacity number is seeded, and the AI runtime is not wired.
  See the Phase 12 record in the traceability document.
- Phase 13 inventory and reconciliation is independently accepted
  (2026-11-17) and inactive, on the accepted Phase 12 checkpoint `4efabb05`;
  local checkpoint `26468456`. The findings of its CONDITIONAL PASS review (H1,
  M1, M2, L1, L2) and the re-acceptance finding M2b were remediated, and the
  narrow re-acceptance returned PASS. Pure projections give the Usage & Billing data for one
  organization billing account (optional member view) from the Phase 3–12
  records; a read-only comparison classifies every legacy compatibility field
  with the D16 classes; an enforced inventory lists every legacy billing
  writer on the billing line and the unified line. Nothing is written, no
  migration is added, and live readers are unchanged until Phase 17. See the
  Phase 13 record in the traceability document.
- Phase 14 legacy backfill is implemented locally, inactive, on the accepted
  Phase 13 checkpoint `26468456` (migration `d2f4a6c8e0b3`); its independent
  acceptance returned FAIL (B1, B2) and the remediation is ready for narrow
  re-acceptance. Gate 1: legacy stored integers and ledger integers are the
  same internal unit (1,000 per displayed credit; 3,600,000 per provider
  dollar), copied as stored. Each organization's billing account, payer, and
  payment receipts are established once from ranked evidence; then
  evidence-ranked `migration_opening` lots, each legacy source at most once
  across all accounts and each traceable to its real legacy row, are checked
  against the exact D16 conservation equations and the Phase 13 comparison;
  anything unexplained is quarantined. Purchased credit keeps its original
  terms (packs and the 300K offer stay non-expiring). Per the founder
  decisions of 2026-11-18, every legacy payment row is preserved in an
  immutable legacy archive (test activity only on an explicit founder
  attestation; never a financial transaction, nothing missing filled in), and
  each account's legacy plan, subscription, entitlements, and seats are mapped
  from existing records, with subscription dates, paid seats, and payment
  details left unresolved for a later, separately authorized Stripe read. No
  production data, Stripe, or AI provider is touched. See the Phase 14 record
  in the traceability document.
- Runtime prerequisite: before any Phase 4 runtime activation, the production
  backend must run Python 3.10 or later, with Python 3.12 preferred to match CI
  and the Docker image. `app/billing_entitlements.py` uses `X | None` type
  annotations that fail to import on Python 3.9. The Phase 4 models imported at
  startup do not use that syntax, so the inactive foundation does not affect
  current startup.
- The accepted schema, models, and tests remain additive and disconnected from
  legacy runtime billing readers and writers.
- No production or staging system was accessed.
- No paid AI call was made.
- PR #27 remains open and unmodified.
- Exact communication wording remains a later review item.
- No numerical short-term capacity limit is approved.
- The original 18 phases are authoritative; Phase 2A–2G are cross-referenced
  program gates, not a replacement roadmap.
- No backfill, dual write, ledger activation, cutover, or customer-facing
  behavior change is authorized. See the status-preserving
  [phases 2–5 proposal](phase-2-5-implementation-proposal.md).
