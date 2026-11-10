# Billing Architecture Phase 1

Status: **Proposed for review; no implementation authorized**

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

The target architecture replaces that overlap with four deliberately separate
authorities:

1. a financial transaction authority for money and Stripe evidence;
2. an entitlement authority for capabilities, plans, contracts, and seats;
3. one append-only credit ledger for every funded lot, hold, reservation,
   settlement, expiration, release, reversal, and recovery; and
4. an AI-operation authority that binds one usable result to one reservation
   and settlement without becoming a balance store.

Read models project those authorities. Authentication, billing status,
organization resolution, and AI preflight become pure reads. Stripe remains an
external payment processor and evidence source, not Jaspen's internal state
machine. Customer communications are emitted from an audited outbox and never
decide financial, entitlement, or credit state.

The replacement preserves customer money, funded credits, personal and
organization ownership, saved decisions and plans, plan capabilities through
valid paid periods, credit-pack value, promotional value, audit evidence, and
the regression intent of PR #27. It does not preserve accidental reset-on-read,
negative balances, recurring rollover, account-wide dispute penalties, direct
balance edits, or duplicated compatibility state as authorities.

Phase 2 is **not ready to begin**. This ADR must be reviewed, and the stop-class
conflicts in [current-state-inventory.md](current-state-inventory.md#d20-newly-discovered-conflicts-and-stop-register)
must be explicitly accepted as consolidation work. Phase 1 has not changed
application behavior, schema, migrations, production data, deployment state,
or PR #27.

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

## Acceptance assessment

The design assigns one target authority to every approved rule, maps all 14
approved policies and lifecycle confirmations to components and tests, defines
funding ownership and deterministic precedence, and provides sunset conditions
for compatibility projections. The migration specification is balance
preserving and explicitly rejects silent data repair.

Phase 1 documentation is complete for review. Acceptance remains pending until
the ADR and stop register receive human review. No claim is made that the
current implementation satisfies the target architecture.

## Scope guardrails

- No Phase 2 implementation is included.
- No schema, migration, application, test, or customer-facing wording changed.
- No production or staging system was accessed.
- No paid AI call was made.
- PR #27 remains open and unmodified.
- Exact communication wording remains a later review item.
