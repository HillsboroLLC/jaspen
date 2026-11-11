# Billing Architecture Phase 1

Status: **Phases 1–4 complete and inactive (Phase 4 in `develop`, not deployed); Phase 5.1 implemented and verified on its branch**

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
preserve accidental reset-on-read, negative balances, recurring rollover,
account-wide dispute penalties, direct balance edits, or duplicated
compatibility state as authorities.

Founder architecture approval was recorded on 2026-11-09 for ADR-0001,
STOP-01 through STOP-25, the organization-first model, and the authoritative
18-phase roadmap. Phases 2.1, 2.2, 2.3, and 3 were subsequently authorized,
implemented, independently verified, and accepted as additive, inactive
foundations. Phase 4 was then implemented and independently verified on
PostgreSQL 18.6 (commit `24c14d5`), merged into `develop` at `14cb0ab6` with CI
passing, and closed; it is not deployed or activated. Phase 5.1 (minimal-data
external event inbox) is implemented and verified on its branch and is not
connected to any webhook. The phases 2–5 proposal continues to identify separately
reviewable, reversible increments; no backfill, runtime activation, or cutover
is bundled. The stop-class conflicts in
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
- Phase 5.1 is implemented and verified on its branch. The inbox is not
  connected to live Stripe webhooks and stores no card or unnecessary personal
  data (see the Phase 5.1 record in the proposal).
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
