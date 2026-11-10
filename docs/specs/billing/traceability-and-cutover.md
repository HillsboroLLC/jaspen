# Policy Traceability, Migration, Regression, and Cutover

## D02 Policy-to-component traceability

Target test IDs are specifications for Phase 2, not tests added in Phase 1.

| Policy | Target authority/components | State machine/rule | Target tests |
|---|---|---|---|
| P01 Annual paid annually, monthly anchored allocations | Financial lines, entitlement, credit period/lot | D07 annual anchor and monthly period opening | T-PERIOD-03, T-PERIOD-04, T-ORDER-06 |
| P02 Free 300 monthly from creation anchor, no rollover | Billing account, free entitlement, credit periods | D07 Free anchor; D06 expiration | T-PERIOD-01, T-PERIOD-02 |
| P03 Paid upgrade proration; Free-to-paid full period | Financial authority, schedule, credit ledger | D07 formula; D08 upgrade | T-PLAN-01 through T-PLAN-05 |
| P04 Dunning preserves valid capabilities/credits, no unfunded value | Financial subscription state, entitlement, period allocator | D07 funded/unfunded; D08 downgrade failure | T-DUNNING-01 through T-DUNNING-05 |
| P05 One-time partial refund proportionally reverses purchase-specific unused credits | Financial lines, cumulative refund case, ledger | D10 partial-refund formula | T-REFUND-01 through T-REFUND-05 |
| P06 Subscription refund requires disposition | Refund case, entitlement review | D10 subscription disposition | T-REFUND-06, T-REFUND-07 |
| P07 Trials/comps require approved offers | Entitlement definitions, offer/redemption, lots | D07 approval evidence | T-OFFER-01 through T-OFFER-04 |
| P08 Admin authority/capabilities/data/funding separate | Permission service, entitlement, ledger, risk | D11; D20 STOP-12/13 | T-ADMIN-01 through T-ADMIN-06 |
| P09 Enterprise by executed organization-owned contract | Contract authority, org billing account, entitlement/lots | D07 evidence transition | T-ENTERPRISE-01 through T-ENTERPRISE-05 |
| P10 Renewal-timed downgrade; seats separate from occupancy | Scheduled changes, entitlement, seat commitment | D08 downgrade; D09 seats | T-PLAN-06 through T-PLAN-12, T-SEAT-01 through T-SEAT-07 |
| P11 Dispute opened/pending/won/lost, source hold, absorbed shortfall, no account penalty | Financial case, ledger holds, risk separation | D10 dispute/recovery | T-DISPUTE-01 through T-DISPUTE-12 |
| P12 No recurring rollover; expiration-first; purchased protected | Credit lots and allocation engine | D06 allocation/expiry | T-LEDGER-01 through T-LEDGER-08 |
| P13 Integer UTC rounding, zero floor, taxes/fees excluded, bonus proportional | Period calculator, refund attribution, ledger invariants | D06/D07/D10 formulas | T-MATH-01 through T-MATH-08 |
| P14 Evidence-backed legacy/Enterprise migration and `legacy_unattributed` | Migration reconciler and review queue | D16 | T-MIGRATE-01 through T-MIGRATE-12 |
| P15 Mixed invoices use line attribution | Financial transaction/line authority | D10 mixed invoice | T-FIN-01 through T-FIN-06 |
| P16 Recovery never exceeds original entitlement | Recovery case and ledger invariant | D10 recovery | T-RECOVERY-01 through T-RECOVERY-05 |
| P17 One active schedule and deterministic precedence | Scheduled-change authority | D08 precedence | T-SCHEDULE-01 through T-SCHEDULE-09 |
| P18 Seat reduction blocked above occupancy; preserve work; notify/audit | Seat commitments, membership projection, outbox | D09/D12 | T-SEAT-04 through T-SEAT-10, T-MSG-03 |
| P19 Authorized proportionate risk restrictions only | Risk authority and permissions | D11 | T-RISK-01 through T-RISK-10 |
| P20 Communications event-driven/idempotent/non-authoritative | Domain events and outbox | D12/D13 | T-MSG-01 through T-MSG-08 |
| P21 Reads/auth/preflight/org resolution never mutate | Projection APIs and command/query split | ADR invariant | T-READ-01 through T-READ-08 |
| P22 Saved work never deleted by billing transitions | Entitlement/seat/risk handlers; data layer excluded | D08/D09/D11 | T-DATA-01 through T-DATA-06 |
| P23 Personal/org/purchase/promo/trial/internal funding stays specific | Billing accounts, lots, allocation | D06 ownership/taxonomy | T-OWNER-01 through T-OWNER-10 |
| P24 One usable result, one operation-bound settlement | AI operation and ledger | D06 operation lifecycle | T-AI-01 through T-AI-10 |

### End-to-end behavior ownership

| Behavior | Input/evidence | Command owner | Persistence | Reader/projection | Communication |
|---|---|---|---|---|---|
| Subscribe/renew | paid invoice lines | Financial -> Entitlement -> Credit Period | financial facts, entitlement, period, lot/entries | billing/access/usage projections | payment/period events |
| Upgrade | authenticated command + paid proration invoice | Schedule/Financial -> Entitlement/Ledger | schedule history, line, prorated lot | plan/credits projection | upgrade event |
| Downgrade/cancel | authenticated command + renewal outcome | Scheduled Change | schedule + entitlement transition | plan/status projection | schedule/effective event |
| Consume AI | operation request and validated usable result | AI Operation -> Ledger | operation, reservation allocations, settlement | usage/balance projection | low/empty balance event if approved |
| Refund | cumulative refund and line evidence | Financial Case -> Ledger/Entitlement disposition | refund facts, case, deltas | transaction/balance projection | refund event |
| Dispute/recovery | processor case/version | Financial Case -> Ledger; optional Risk | case, hold/reversal/release/recovery | case/balance projection | dispute events |
| Seat change | org admin command, occupancy, payment | Seat Commitment | schedule/history | seat projection | blocked/approaching/applied events |
| Internal grant | authorized actor and approved source | Entitlement/Ledger | grant evidence and entries | capability/balance projection | audited internal/customer event as approved |
| Enterprise | executed contract | Contract -> Entitlement/Ledger | contract evidence, schedule, lots | org access/billing projection | contract lifecycle event |

## D16 Migration reconciliation specification

### Preconditions

- ADR-0001 and D20 consolidations reviewed.
- Additive schema and downgrade plan separately approved.
- Snapshot/rehearsal uses local or approved non-production fixtures only until a
  separate production migration authorization exists.
- All current writers from D04 are instrumented or frozen for a consistent
  source snapshot.
- No current field is deleted during migration.

### Evidence-ranked source mapping

Use the strongest available evidence in this order:

1. immutable payment/invoice/line and external references;
2. persistent entitlement/grant/transaction rows;
3. organization/user JSON meters and anchored timestamps;
4. user combined counter and plan/status;
5. audited admin events and approved internal records;
6. `legacy_unattributed` only after documented reconciliation review.

Never fabricate an invoice, contract, offer, owner, expiry, or source to make a
row fit.

### Opening-balance algorithm

For each explicit target billing account and owner:

1. Determine owner from payment/entitlement/org membership evidence, never the
   current active organization alone.
2. Rebuild persistent purchased/promotional lots from grants and transactions.
3. Derive current recurring remainder independently from personal or
   organization meter evidence.
4. Compare the reconstructed total to `User.credits_remaining` for every
   affected user and to organization shared-pool projections.
5. Classify each difference as known projection duplication, known stale
   counter, evidence-backed adjustment, or unresolved.
6. Create idempotent `migration_opening` entries only for preserved value that
   is not already represented.
7. Use `legacy_unattributed` only for unresolved source attribution with known
   owner and amount. Quarantine unknown owner or contradictory evidence.
8. Record source hashes, evidence references, calculation, reviewer, and
   migration run ID.

### Balance conservation equations

For each owner at snapshot time:

```text
target_available + target_active_holds
  = accepted_legacy_recurring_remaining
  + accepted_legacy_persistent_remaining
  + approved_migration_adjustments

target_original_purchased_by_source
  = accepted_grant_original_by_source

target_settled_usage_by_operation
  = accepted operation/usage evidence after duplicate elimination
```

The first equation is exact in internal integer credit units. No tolerance is
allowed. Financial amounts reconcile exactly in minor currency units by
currency; taxes, fees, discounts, principal, refunds, and disputes are separate
columns and cannot net invisibly.

### Special cases

- **Negative legacy meter:** quarantine; target balance remains zero or
  positive and no debt entry is created without approved policy.
- **Combined counter lower than proven purchased balance:** preserve proven
  purchased balance and quarantine evidence conflict; do not silently reduce.
- **Combined counter higher than all evidence:** `legacy_unattributed` only
  after review; otherwise block account cutover.
- **Persistent grant transaction sum differs from remaining:** transaction log
  and external evidence are reconciled; do not choose whichever favors a clean
  run without review.
- **Shared pool copied into multiple user counters:** recognize as projection
  duplication and create one organization lot, not per-user lots.
- **Enterprise:** require executed organization-owned contract evidence. A
  plan label or null balance is insufficient.
- **Annual subscription:** payment evidence funds a term, then monthly periods
  are reconstructed from anchor; future unopened periods are not available.
- **Expired recurring value:** never migrate as available purchasing power.
- **Active dispute:** migrate case state and source hold before exposing balance.
- **In-flight AI reservation:** pause or drain operations; never infer a hold
  from a stale combined counter.

### Reconciliation reports

Each rehearsal produces:

- counts and sums by owner type, source, currency, plan, and period;
- pre/post available, held, settled, expired, and reversed totals;
- every duplicate external reference and idempotency conflict;
- every unresolved owner/source/expiry/contract/invoice-line conflict;
- sampled account proofs showing input evidence and target entries;
- compatibility projection comparison for every API field;
- a deterministic rerun showing zero new entries.

Any unexplained difference blocks that account and the global write cutover.

### Rollback

Before write cutover, target tables and projections may be discarded using the
approved migration downgrade while legacy remains authoritative. After write
cutover, rollback means stopping new commands, preserving the append-only
ledger, and restoring service from its entries/projections; it never means
rewriting ledger history or copying counters backward without a reviewed plan.

## D17 Regression traceability matrix

### Existing intent to preserve

| Existing test/evidence | Preserved intent | Target suite |
|---|---|---|
| `test_credit_pack_*adds_tokens_once`, duplicate/cross-type/concurrent tests | one purchase creates one lot across delivery races | T-ORDER-01..05, T-OWNER-05 |
| `test_credit_pack_survives_monthly_reset` | purchased value does not expire with recurring period | T-LEDGER-03 |
| `test_refund_reverses_only_unused_pack_value_and_keeps_audit_history` | source-specific unused reversal and audit history | T-REFUND-01..05 |
| limited-time idempotency and refund tests | offer grant is independent, idempotent, reversible by source | T-OFFER-01..04, T-REFUND-04 |
| `test_monthly_credits_are_consumed_before_founder_credits` | expiring value before purchased/persistent | T-LEDGER-01..04 |
| `test_reservation_release_restores_only_the_current_debit_sources` | exact source restoration | T-AI-04..07 |
| personal/team-pool tests | personal value cannot be spent by teammate | T-OWNER-01..06 |
| AI governance idempotency/validation/reversal tests | charge once only for usable retained result | T-AI-01..10 |
| payment-recording idempotency tests | financial object is recorded once | T-FIN-01..04 |
| billing annual/seat tests | selected interval and paid seat product retained | T-PERIOD-03, T-SEAT-01..03 |
| PR #27 added tests | status/auth reads preserve and honestly report usage | T-READ-01..04, T-ADMIN-02 |

### Required target regression cases

| Test ID range | Required assertions |
|---|---|
| T-READ-01..08 | repeat auth/status/preflight/org resolution under due/empty/legacy/admin/org states; database authoritative rows and event counts unchanged |
| T-PERIOD-01..04 | Free creation anchor, month-end clamp, no rollover, annual monthly allocations with unopened future periods |
| T-PLAN-01..12 | Free-to-paid full lot; paid upgrade floor/UTC/payment gate; monthly/annual downgrade; failure/later success; anchor stable; cancel/upgrade/supersede precedence |
| T-DUNNING-01..05 | capabilities and funded credits retained; no new unfunded credits; terminal transition separated; unrelated saved work untouched |
| T-LEDGER-01..08 | expiry-first ordering, purchase protection, exact allocation, zero floor, held lot expiry, deterministic ties, replay invariant |
| T-OWNER-01..10 | personal/org/source isolation, explicit payer, no active-org leakage, shared pool single ownership, internal/trial/promo isolation |
| T-AI-01..10 | operation fingerprint, concurrent reserve, validation failure release, exact settle, supplemental failure, persistence compensation, replay |
| T-REFUND-01..07 | cumulative partial/full purchase refund, taxes/fees excluded, bonus proportional, consumed floor, subscription disposition |
| T-DISPUTE-01..12 | open/pending hold, won release, lost reversal, consumed shortfall absorbed, mixed-line attribution, expiration while held, unrelated/future funding unchanged |
| T-RECOVERY-01..05 | exact prior reversal reference, cumulative delta, original cap, expired-lot rule, replay |
| T-SCHEDULE-01..09 | one active schedule, compatible supersede, paid upgrade supersede, failed upgrade no supersede, cancellation precedence, browsing no-op, history retained |
| T-SEAT-01..10 | commitment vs occupancy, blocked reduction, no member/work deletion, contract exception, payment failure, later success, idempotent audited notices |
| T-RISK-01..10 | permission denied/allowed, scoped restriction, complete evidence fields, urgent review record, release, no authority leakage |
| T-MSG-01..08 | post-commit outbox, dedupe, retry, delivery failure independence, non-authoritative payload, audit history |
| T-MIGRATE-01..12 | exact balance/source/owner/financial reconciliation, shared-pool dedupe, annual periods, Enterprise evidence, unattributed review, rerun no-op |
| T-DATA-01..06 | upgrades/downgrades/cancel/dunning/seat/risk transitions never delete or reassign saved work |
| T-MATH-01..08 | integer UTC floor, month-end anchors, zero floor, cumulative ratios, minor units, no floating-point drift |
| T-ADMIN-01..06 | admin permission/capability/data/funding independent; all adjustments ledgered; admin reads pure and usage visible |
| T-ENTERPRISE-01..05 | contract ownership/effective term/funding schedule, missing evidence quarantine, no consumer-status coupling |
| T-OFFER-01..04 | only approved versioned trial/promo/comp offers grant entitlement/lots; expiry and owner exact |
| T-FIN-01..06 | invoices/lines/payment/refund/dispute/recovery immutable and exactly attributed, including mixed invoices |
| T-ORDER-01..06 | duplicate, cross-type, out-of-order, concurrent, stale, and manual replay converge; annual allocation ordering safe |

### Acceptance gates for the target implementation

- Every command produces one authoritative transition or a typed no-op.
- Every read test observes zero writes.
- Every compatibility field equals its projection proof.
- No legacy direct writer remains enabled at final cutover.
- Ledger sums, financial sums, and source/owner partitions reconcile exactly.
- Failure injection at each external/transaction boundary preserves invariants.

## D18 Phase dependency and cutover map

This map defines dependencies; it does not authorize any phase.

```text
Phase 1 (this package; review required)
  |
  +--> Phase 2A: additive foundations
  |      billing accounts, financial lines, entitlement definitions/instances,
  |      credit lots/ledger, schedules, inbox/outbox, risk permissions
  |
  +--> Phase 2B: pure projections and reconciliation tooling
  |      no write cutover; compare against legacy
  |
  +--> Phase 2C: migration rehearsal and conflict review
  |      exact balances/owners/sources/contracts; rerun idempotency
  |
  +--> Phase 2D: command-by-command writer cutover
  |      external events -> funding -> AI reservations -> admin -> schedules/seats
  |
  +--> Phase 2E: reader cutover
  |      auth/status/preflight/org/frontend/admin use pure projections
  |
  +--> Phase 2F: legacy freeze and observation
  |      compatibility projector only; zero legacy writes/drift
  |
  +--> Phase 2G: reviewed retirement
         remove legacy writers/aliases/JSON authority and decide PR #27 disposition
```

### Dependency gates

| Stage | Must exist first | Exit evidence |
|---|---|---|
| 2A foundations | reviewed ADR/D20; approved schema/migration plan | constraints, permissions, idempotency registry, unit tests |
| 2B projections | ledger/entitlement/financial read APIs | pure-read tests and field proofs |
| 2C rehearsal | deterministic migration and reports | exact reconciliation, reviewed exceptions, rerun no-op |
| 2D external/financial cutover | inbox, lines, cumulative cases | Stripe race/order/refund/dispute tests |
| 2D funding cutover | entitlement/period/lot authority | anchor/proration/rollover/source tests |
| 2D AI cutover | operation-linked reservation allocations | usable-result and concurrency tests |
| 2D admin/risk cutover | explicit permissions and adjustment sources | separation/audit tests |
| 2D schedule/seat cutover | state machines and precedence | downgrade/cancel/seat tests |
| 2E readers | stable projections and versions | auth/status/preflight/org zero-write tests |
| 2F observation | all command writers cut over | zero legacy writes, zero drift, operational replay evidence |
| 2G retirement | reviewed observation and rollback plan | consumer inventory empty; archive/export retained |

### Cutover ordering rationale

Financial and event identity must precede credit grants so one external fact
cannot fund twice. Credit lots must precede AI reservations so consumption has
an owner and source. Explicit internal/risk permissions must precede removal of
admin shortcuts. Schedules and seats depend on entitlement and financial
states. Readers move only after projections are complete. Legacy writers are
retired only after the projector proves parity; dual writers are never a steady
state.

### Phase 2 readiness

Phase 2 is not authorized and is not yet ready for authorization because:

1. ADR-0001 has not been reviewed;
2. the D20 consolidation/stop register has not been explicitly accepted;
3. additive schema and migration mechanics have not been reviewed;
4. exact terminal subscription policy and communication wording remain later
   approved review items where the baseline intentionally supplies no invented
   deadline or wording.

Once those prerequisites are met, Phase 2A can be authorized independently.
No later cutover stage should be bundled into that authorization.
