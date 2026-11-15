# Policy Traceability, Migration, Regression, and Cutover

## D02 Policy-to-component traceability

Target test IDs are specifications for Phase 2, not tests added in Phase 1.

| Policy | Target authority/components | State machine/rule | Target tests |
|---|---|---|---|
| P01 Annual paid annually, monthly anchored allocations | Financial lines, entitlement, credit period/lot | D07 annual anchor and monthly period opening | T-PERIOD-03, T-PERIOD-04, T-ORDER-06 |
| P02 Free configured allowance monthly from organization creation anchor, no rollover | Organization billing account, free entitlement, credit periods | D07 Free anchor; D06 expiration | T-PERIOD-01, T-PERIOD-02 |
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
| P23 Every customer is an organization; purchase/promo/trial/internal/member-attributed funding stays specific | Organization billing account, billing roles, lots, allocation | D06 ownership/taxonomy | T-OWNER-01 through T-OWNER-10 |
| P24 One delivered response, one operation-bound settlement of its actual billable usage; undelivered usage absorbed with evidence | AI operation and ledger | D06 operation lifecycle | T-AI-01 through T-AI-10 |
| P25 Effective-dated pricing; no retroactivity; notify before customer-impacting change | Pricing policy versions, AI operation, outbox | D21 | T-PRICE-01 through T-PRICE-10 |
| P26 Credits and short-term capacity are independent; tier-aware and provider-independent | Capacity policy/authorization, AI operation | D22 | T-CAPACITY-01 through T-CAPACITY-12 |
| P27 Usage & Billing projection, 20% warning once per period, BALANCE retained | Pure projections, outbox, UI adapter | D12/D23 | T-USAGE-01 through T-USAGE-10 |
| P28 Interrupted work resumes from last completed step without duplicate charge | AI operation checkpoints, session persistence, ledger | D06/D22/D23 | T-AI-11 through T-AI-16 |

### End-to-end behavior ownership

| Behavior | Input/evidence | Command owner | Persistence | Reader/projection | Communication |
|---|---|---|---|---|---|
| Subscribe/renew | paid invoice lines | Financial -> Entitlement -> Credit Period | financial facts, entitlement, period, lot/entries | billing/access/usage projections | payment/period events |
| Upgrade | authenticated command + paid proration invoice | Schedule/Financial -> Entitlement/Ledger | schedule history, line, prorated lot | plan/credits projection | upgrade event |
| Downgrade/cancel | authenticated command + renewal outcome | Scheduled Change | schedule + entitlement transition | plan/status projection | schedule/effective event |
| Consume AI | operation request and delivered response | AI Operation -> Ledger | operation, reservation allocations, settlement | usage/balance projection | low/empty balance event if approved |
| Refund | cumulative refund and line evidence | Financial Case -> Ledger/Entitlement disposition | refund facts, case, deltas | transaction/balance projection | refund event |
| Dispute/recovery | processor case/version | Financial Case -> Ledger; optional Risk | case, hold/reversal/release/recovery | case/balance projection | dispute events |
| Seat change | org admin command, occupancy, payment | Seat Commitment | schedule/history | seat projection | blocked/approaching/applied events |
| Internal grant | authorized actor and approved source | Entitlement/Ledger | grant evidence and entries | capability/balance projection | audited internal/customer event as approved |
| Enterprise | executed contract | Contract -> Entitlement/Ledger | contract evidence, schedule, lots | org access/billing projection | contract lifecycle event |
| Authorize AI use | org/work context + request + pricing/capacity policy | AI Operation -> Capacity -> Ledger | operation/checkpoint, capacity decision, reservation | session/usage/capacity projection | low/empty/capacity event |
| Change pricing policy | approved version + affected-customer analysis | Pricing Policy -> Outbox | immutable policy, effective time, notice evidence | current/future operation policy | advance notice when impact exists |

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

For each explicit target organization and billing account:

1. Establish one organization for every customer, including single-member
   accounts, from payment/entitlement/membership evidence; never choose a payer
   from the current active organization alone.
2. Rebuild persistent purchased/promotional lots from grants and transactions.
3. Derive recurring remainder from the strongest user/org meter evidence and
   map it to the organization billing account. Preserve member attribution or
   member-only eligibility where evidence requires it; do not create a personal
   billing account.
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

- counts and sums by organization billing account, source, currency, plan, and period;
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
| personal/team-pool tests | legacy member-attributed value cannot be spent by a teammate; migrate it within one org-owned billing account | T-OWNER-01..06 |
| AI governance idempotency/validation/reversal tests | charge once only for a delivered response; legacy release/reversal paths are replaced in Phase 12 | T-AI-01..10 |
| `test_ai_economics.py`, `test_ai_governance.py` | provider cost, 3,600-credit policy, attempts/fallback, operation settlement | T-PRICE-01..10, T-AI-01..16 |
| `test_shared_ai_rate_limits.py` | blocked requests do not charge, shared Redis works, counters isolate users | T-CAPACITY-01..12 |
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
| T-OWNER-01..10 | universal org creation, explicit org payer, billing-role separation, member attribution, no active-org leakage, shared pool single ownership, internal/trial/promo isolation |
| T-AI-01..16 | operation fingerprint, concurrent reserve, no-usage release, undelivered-response release with absorbed-usage evidence, delivered-response exact settle, fallback charges only the delivering attempt, delivered response still charged after a nonessential-step failure, uncertain usage reconciled and never charged, quality never affects billability, supplemental failure, tool-loop accounting, checkpoint/resume, replay |
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
| T-PRICE-01..10 | exact provider/model arithmetic, rounding/conversion version, unknown model fail-closed, future-provider adapter parity, effective dates, no retroactivity, in-progress binding, customer-impact classification and notice evidence |
| T-CAPACITY-01..12 | org/member windows, concurrency, tier priority, provider pressure/fallback, abuse/runaway guard, no credit deduction, credit purchase no bypass, available-again response |
| T-USAGE-01..10 | ledger-synchronized totals/history/session usage, recurring vs purchased, refresh/payment/term dates, interval/time zone, 20% warning once per period, distinct capacity/exhaustion copy, BALANCE retained |

### Phase 5.3 implementation traceability

Status: **Independently accepted on PostgreSQL 18.6; integration into `develop`
pending; inactive.** Acceptance completed with 129 passed, 0 failed, and 0
skipped. The recorder has no live runtime caller, and acceptance did not
authorize deployment or billing activation. The authorized boundary remains
case persistence and recording only. At that acceptance boundary, Phase 5.4
domain events/outbox and Phase 9 credit effects remained out of scope.

| Requirement | Component/contract | Regression coverage |
|---|---|---|
| Additive case projection, append-only versions, source attribution and ledger-effect references | Migration `d3e5a7b9c1f4`; `FinancialCase`, `FinancialCaseEvent`, `FinancialCaseEventLine`, `FinancialCaseEventLedgerEntry` | `test_phase53_migration_is_linear_additive_and_model_consistent`; `test_empty_downgrade_removes_only_phase53_tables`; `test_downgrade_refuses_case_evidence` |
| Exact Phase 5.1 inbox and Phase 5.2 financial source, account, currency and line relationships | `billing_financial_cases.record_financial_case_event()` plus migration guards | `test_case_recording_is_idempotent_immutable_and_does_not_touch_ledger`; `test_conflicted_inbox_evidence_cannot_support_a_case`; `test_case_ledger_links_enforce_account_and_effect_type` |
| Stable replay identity, conflict detection, stale ordering and cumulative state updates | Provider financial object/version identity; current case projection backed by an immutable event | `test_case_recording_is_idempotent_immutable_and_does_not_touch_ledger`; `test_case_event_rejects_reused_version_with_different_evidence`; `test_stale_refund_case_version_is_ignored`; `test_same_effective_time_uses_received_time_as_ordering_tiebreaker`; `test_dispute_transitions_append_versions_and_reopen_from_terminal` |
| Cumulative principal reconciles exactly to its linked Phase 5.2 refund/dispute transaction snapshot | Each immutable provider object version is a cumulative snapshot; its signed transaction principal equals the negated case cumulative principal; corrections/reversals append new versions | `test_case_principal_matches_signed_cumulative_financial_snapshot`; `test_database_rejects_case_principal_mismatch`; `test_postgres_database_rejects_case_principal_mismatch` |
| Exact integer-minor-unit line attribution and auditable source references per case version | Append-only `FinancialCaseEventLine`; event links to financial transaction and inbox evidence; current versions across distinct cases share source-line capacity; historical versions remain immutable but do not consume current capacity | `test_case_preserves_exact_line_allocations_and_audit_references`; `test_current_case_attributions_release_capacity_on_cumulative_correction`; `test_sequential_current_cases_cannot_overattribute_source_line`; `test_database_rejects_aggregate_overattribution`; `test_postgres_database_rejects_aggregate_overattribution`; `test_postgres_concurrent_cases_cannot_overattribute_source_line` |
| Explicit subscription-refund disposition; no inferred attribution or entitlement/ledger mutation | D10 disposition is retained in the immutable event; caller-supplied exact line allocations; Phase 3 remains the sole ledger authority | `test_subscription_refund_requires_explicit_disposition_and_rollback_is_atomic`; `test_case_attribution_cannot_exceed_eligible_source_principal`; `test_case_recorder_has_no_live_runtime_callers` |
| One immutable case-version owner per Phase 3 ledger entry | Database uniqueness prevents one ledger entry from being claimed by unrelated case versions; multiple entries per case version remain allowed | `test_ledger_entry_has_one_case_version_owner`; `test_postgres_ledger_entry_has_one_case_version_owner`; `test_case_ledger_links_enforce_account_and_effect_type` |
| PostgreSQL concurrency, deferred line reconciliation, immutable evidence and transaction atomicity | Per-source transaction fence serializes current-attribution checks; distinct-case inserts and simultaneous competing corrections are verified under READ COMMITTED, REPEATABLE READ, and SERIALIZABLE; deferred projection/reconciliation constraints; top-level `created_xid` event seal | `test_postgres_concurrent_duplicate_case_versions_converge`; `test_postgres_concurrent_cases_cannot_overattribute_source_line`; `test_postgres_competing_case_corrections_preserve_source_capacity`; `test_postgres_case_recording_keeps_event_lines_atomic_across_savepoint`; `test_postgres_deferred_case_line_reconciliation_rejects_partial_commit` |

PostgreSQL-specific cases use only the disposable `TEST_DATABASE_URL` fixture
and skip when it is unavailable. The Phase 5.1/5.2 T-INBOX-01..03 hardening gate
below is unchanged and remains a prerequisite to inbox activation.

**Deferred Phase 9 dependency:** Phase 5.3 stores, validates, and preserves
exact caller-resolved line amounts; it does not calculate D10 proportional
refund/dispute allocations. Before Phase 9 financial effects are implemented,
that phase must specify a deterministic integer-minor-unit residual/tie-break
rule for proportional dispute allocation and test D10's tax/fee exclusions,
discounted mixed-line attribution, cumulative deltas, replay/concurrency, and
isolation of unrelated funding. Phase 9 must link each resulting ledger effect
to the immutable case version without rewriting its evidence, and establish
DB-verifiable source/lot provenance atomically with that ledger-effect link.

### Phase 5.4 implementation traceability

Status: **Independently accepted on PostgreSQL 18.6; integration into `develop`
pending; inactive.** The additive migration adds append-only
account-scoped domain events, deduplicated outbox obligations, and auditable
delivery attempts. No delivery worker, live route/webhook caller, or Phase 12
integration is included. Recording and attempt-state changes remain
caller-owned transactions; no function commits or contacts a provider.

| Requirement | Component/contract | Regression coverage |
|---|---|---|
| Record committed domain-event identity and minimal references atomically with account-scoped outbox obligations | Migration `e4b7c2d9a1f0`; references are stored once on `DomainEvent` and outbox rows link by event ID; `billing_outbox.record_domain_event()` | `test_event_and_outbox_are_atomic_immutable_idempotent_and_auditable`; `test_revision_extends_phase53_and_models_match_additive_schema`; SQLite and PostgreSQL variants of `test_phase52_to_phase54_migration_chain_and_empty_rollback` |
| Stable event replay identity, conflict on changed facts, reference-only JSON, and canonical D13 delivery dedupe key | Unique `event_key`, request fingerprint over event and delivery facts, database-enforced unique nonempty string references, canonical `message:<event>:<template-version>:<account>:<channel>` key | `test_event_and_outbox_are_atomic_immutable_idempotent_and_auditable`; `test_database_enforces_reference_dedupe_and_account_contracts`; PostgreSQL direct-SQL variant; concurrent duplicate case in `test_postgres_outbox_skip_locked_claims_and_trigger_projection` |
| Immutable event evidence, guarded outbox state projection, one terminal attempt result, retries, lease recovery, audit history, and safe downgrade | Migration row and `TRUNCATE` triggers; consistently ordered PostgreSQL exclusive downgrade locks; `CommunicationOutboxAttempt`; claim/result services | `test_event_and_outbox_are_atomic_immutable_idempotent_and_auditable`; `test_expired_claim_is_audited_and_cannot_complete_after_reclaim`; `test_postgres_truncate_cannot_remove_phase54_evidence`; `test_postgres_downgrade_waits_for_concurrent_insert_and_refuses` |
| Concurrent delivery claims do not claim the same row | PostgreSQL `FOR UPDATE SKIP LOCKED`; no transport invocation | `test_postgres_outbox_skip_locked_claims_and_trigger_projection` |
| Delivery failure cannot reverse a business transition; no delivery payload becomes financial or entitlement authority | Outbox stores references and template/channel metadata only; transaction ownership stays with the caller; no production caller or worker | `test_event_and_outbox_are_atomic_immutable_idempotent_and_auditable`; `test_outbox_service_has_no_live_runtime_callers` |

Independent PostgreSQL 18.6 technical acceptance passed. The complete Phase
5.1–5.4 suite completed with 144 passed, 0 failed, and 0 skipped; the billing-
foundation regressions completed with 62 passed, 0 failed, and 0 skipped. The
PostgreSQL migration chain and empty downgrade passed, including concurrent
downgrade fencing, direct and cascading immutable-evidence protection,
transaction rollback, idempotent replay, tenant isolation, retry/lease
recovery, and concurrent claims. READ COMMITTED, REPEATABLE READ, and
SERIALIZABLE variants passed. Technical acceptance did not authorize
integration, deployment, a live caller, delivery worker, provider integration,
or billing activation. The Phase 5.1/5.2 T-INBOX-01..03 hardening gate below is
unchanged and remains a prerequisite to inbox activation; Phase 9 credit
effects and Phase 12 AI-operation integration remain deferred under their
approved contracts.

### Phase 6 implementation traceability

Status: **Independently accepted and inactive.** Migration `f5c8d3e0b2a1` and the inactive
`billing_allocations` service add no runtime caller, provider operation,
scheduler, worker, deployment setting, or billing activation.

| Requirement | Component/contract | Regression coverage |
|---|---|---|
| Free allowance uses configured entitlement value and the immutable organization billing-account anchor | Approved effective `EntitlementDefinition`; account-scoped `RecurringCreditAllocation`; canonical `period:free` key | `test_free_period_is_anchored_idempotent_expiring_and_nonrolling`; direct-SQL account/anchor enforcement |
| Monthly subscription allocation requires current paid line evidence and commits one period, lot, grant, and evidence row atomically | Phase 5.2 `FinancialLine`/transaction binding; caller-owned `allocate_recurring_credits()` transaction | `test_monthly_subscription_requires_payment_in_each_period`; valid-boundary and invalid-prior-period database tests; rollback test |
| External financial-line source identity remains distinct from internal funding authority | Phase 5.2 `source_type`/`source_id` retain provider or catalog identity and provider flexibility; `subscription_id` and `entitlement_instance_id` remain the authoritative Phase 6 links; no external-to-internal ID equality rule or historical rewrite | Paid-allocation fixtures use `stripe_price`/price identity separately from matching subscription and entitlement FKs; cross-account and wrong-line service/database tests validate the internal authority links |
| Annual payment opens one anchored monthly allocation at a time without future purchasing power | Annual term/line validation; canonical indexed `period:annual` key; current-period opening fence | `test_annual_payment_opens_monthly_periods_without_future_value` |
| Funding and expiration satisfy D12 without invented delivery defaults | Caller supplies at least one complete obligation; Phase 5.4 atomically records `credit_period_funded` or `credits_expired` and all canonical outbox rows; Phase 6 database triggers reject recurring lots, grants, and expiration effects without matching allocation/event/outbox evidence; replay revalidates the event-plus-obligation fingerprint | `test_free_period_is_anchored_idempotent_expiring_and_nonrolling`; `test_postgres_migrated_schema_funding_and_expiration_replay`; `test_delivery_validation_failure_rolls_back_allocation_and_expiration`; `test_outbox_persistence_failure_rolls_back_funding_and_expiration`; `test_postgres_blocks_direct_recurring_ledger_bypass` |
| Replay and simultaneous allocation converge without cross-tenant evidence or duplicate value | Durable idempotency registry, immutable allocation key/fingerprint, account-first locks, unique period/evidence/lot links | Isolation-parameterized `test_postgres_concurrent_free_period_allocation_converges`; cross-account service and direct-SQL tests |
| Available and held recurring value expires at the fixed period end without rollover | Phase 3 expiration entries retain each held source allocation; Phase 4 period state; database zero-balance and end-time guard | `test_free_period_is_anchored_idempotent_expiring_and_nonrolling`; `test_period_end_expires_available_and_held_value`; `test_postgres_migrated_concurrent_expiration_converges`; `test_postgres_migrated_expiration_races_held_allocation` under READ COMMITTED, REPEATABLE READ, and SERIALIZABLE; migration trigger coverage |
| Evidence is immutable and additive migration downgrade cannot race or discard populated history | Row and statement triggers, including PostgreSQL `TRUNCATE` rejection; consistently ordered exclusive downgrade locks | `test_postgres_constraints_truncate_and_downgrade_race`; empty and populated downgrade tests; full migration-chain rehearsal |

PostgreSQL 18.6 remediation verification completed with 263 Phase 2–6 tests
passing, 0 failed, and 0 skipped. READ COMMITTED, REPEATABLE READ, and
SERIALIZABLE allocation, expiration, and held-value race variants passed. The
full empty-database migration chain, empty Phase 6 downgrade and re-upgrade,
rollback, replay, tenant isolation, immutable evidence, and direct-SQL database
contract checks passed. The final contract resolution preserves external
provider/catalog `source_type`/`source_id` evidence independently from the
authoritative internal subscription and entitlement foreign keys, without a
single-provider restriction or historical evidence rewrite. Independent
Phase 6 independent acceptance is recorded at checkpoint
`ffe4ab0e09f4ca273748aabed6740017f7cc72f3`. Integration, deployment, and
activation remain separate gates. Phase 9 purchases and case credit effects,
and Phase 12 AI-operation integration remain deferred.

### Phase 7 implementation record — plan changes and upgrade proration

Status: **implemented locally and verified for independent review; inactive.**
Migration `a7d9e2f4b6c8` adds organization-owned immutable scheduled-change,
transition-event, and paid-upgrade-allocation evidence. The inactive
`billing_plan_changes` service implements D07/D08/D12/D13: exact integer UTC
paid-upgrade proration, full-period Free-to-paid activation, one active schedule,
explicit compatible supersession, cancellation precedence and resumption,
renewal-paid monthly or annual downgrade, failed-renewal preservation, and
idempotent replay. Caller-supplied delivery obligations, entitlement changes,
Phase 3 ledger effects, Phase 4 projections, Phase 5 evidence, and Phase 6
allocations commit or roll back in the caller-owned transaction.

| Requirement | Component/contract | Regression coverage |
|---|---|---|
| T-PLAN-01..05 paid activation and proration | D07 formula, paid-line authority, unchanged paid anchor, and a zero-capable separately evidenced proration lot | `test_paid_upgrade_uses_integer_utc_floor_and_replays_once`; `test_free_to_paid_opens_full_paid_period_without_proration`; migrated-schema direct guard test |
| T-PLAN-06..12 renewal changes | D08 monthly/annual renewal gate, failed-payment preservation, cancellation at term end, and resume before term end | `test_downgrade_waits_for_payment_then_applies_and_funds`; `test_cancellation_supersedes_downgrade_and_history_is_retained`; migrated-schema downgrade test |
| T-SCHEDULE-01..09 precedence and history | Partial unique one-active fence, immutable append-only transitions, confirmed supersession, and paid-upgrade/cancellation precedence | Schedule validation, replay, direct-SQL fence, and isolation-parameterized competing-command tests |
| Atomic D12/D13 evidence | Canonical registry keys and fingerprints; domain event plus nonempty caller obligations; deferred subscription-definition and proration checks | Rollback tests; migrated-schema direct subscription/lot bypass rejection; concurrent upgrade replay |

The implementation remains disconnected from routes, webhooks, provider APIs,
workers, schedulers, and production configuration. Technical verification does
not authorize integration, deployment, or activation. Local PostgreSQL 18.6
verification passed 276 Phase 2–7 focused tests with 0 failures and 0 skips,
including fully migrated service paths and READ COMMITTED, REPEATABLE READ, and
SERIALIZABLE concurrency variants. The SQLite-focused run passed 160 tests; its
9 skips are PostgreSQL-only Phase 5.3 tests and are covered by the PostgreSQL
run. Empty upgrade/downgrade/re-upgrade and populated downgrade refusal passed.

### Phase 8 implementation record — seat commitments and occupancy

Status: **implemented locally for independent audit; inactive; not accepted.**
Migration `b8c2d4e6f8a1` adds organization-owned immutable seat-commitment
intervals, D09 seat-change commands, append-only transition events, and a
concurrency-only per-subscription fence (the Phase 5.3 fence pattern). The
inactive `billing_seats` service implements D09/D12/D13: paid commitment kept
separate from occupancy projected from active membership; changes authorized
only by an active `billing_owner` or `billing_admin` grant; paid increases from
matching seat-payment evidence; reductions scheduled at the current paid term
end, blocked when paid occupancy exceeds the target, re-evaluated by an
authorized admin, preserved on failed renewal, applied after a paid renewal
only when occupancy fits, and cancellable or supersedable with history kept.
No member, role, project, or saved work is changed, and no credit is touched.

| Requirement | Component/contract | Regression coverage |
|---|---|---|
| T-SEAT-01 commitment vs occupancy | `seat_commitments` intervals; `seat_occupancy()` read of active paid-role membership (existing `build_seat_usage` definition) | `test_commitment_and_occupancy_are_separate_projections`; SQL/Python role-list parity test |
| T-SEAT-02 paid increase | Seat-line payment evidence, delta semantics, one increase per paid line, D08-style supersession of an active reduction | Paid-evidence, replay/conflict, and concurrent-increase tests (three isolation levels) |
| T-SEAT-03..04 reduction and blocked occupancy | Renewal-term target, occupancy decision recorded with evidence, database occupancy recheck | Monthly/annual/month-end tests; blocked/resolve tests; direct-insert occupancy guard test |
| T-SEAT-05..06 payment failure and later success | `awaiting_payment` keeps the commitment; later paid renewal applies only if occupancy fits | Failed-renewal and later-success tests, including incompatible occupancy |
| T-SEAT-07 cancel/supersede | One active reduction per subscription; confirmed supersession; append-only history | Cancellation/supersession test; competing-reduction race test |
| T-SEAT-08..09 no member or work deletion | Service never writes membership, roles, projects, saved work, credits, or legacy seat fields | Lifecycle snapshot test; static write check |
| T-SEAT-10 audited idempotent notices | Every transition records a D12 event with caller obligations; `seat_change_approaching` once per renewal | Notice idempotency test; rollback-on-failure test |
| Permissions and tenant isolation | Explicit billing grant checked in the service and in database guards; organization-scoped command keys | Permission matrix; cross-organization test; database guard bypass tests |

Audit remediation (round 1): each payment line authorizes at most one seat
effect, and evidence must match account, subscription, kind and currency; the
requesting user is persisted and must hold the cited grant on this account,
valid at the request and not ended since; occupancy decisions lock the
organization and its member rows, run only under READ COMMITTED on PostgreSQL
(snapshot isolation fails closed), and are rechecked by the database; SQLite
append-only triggers cover every Phase 8 table. Round 2 (founder-approved
2026-11-14): a versioned seat-funding attribution records, once per paid line,
the seats it supports for one paid term, without reinterpreting the line's
quantity. Included seats come only from the approved plan definition's
`capabilities.included_seats` (fail closed when absent); purchased seats are
separate. Openings, increases and reductions need exact funding; a blocked
renewal keeps the last commitment and records the term's funding as unresolved
until adequate evidence; only a billing owner may authorize paid increases.

Contract exceptions (D09) are deferred to Phase 11, which owns executed-contract
authority (STOP-15). The implementation remains disconnected from routes,
webhooks, provider APIs, workers, schedulers, and production configuration.
Local verification is not acceptance and does not authorize integration,
deployment, or activation.

### Phase 9 implementation record — purchases, refunds, disputes and recoveries

Status: **implemented locally, inactive, awaiting independent audit.**
Migration `e1a3c5b7d9f2` (revises `b8c2d4e6f8a1`) adds three immutable tables.
`app/billing_financial_effects.py` has no route, webhook, worker, or scheduler
caller. Phase 3 stays the only ledger, Phase 5.2/5.3 stay the financial and
case authorities, and Phase 5.4 records every event.

| Requirement | Component/contract | Regression coverage |
|---|---|---|
| Purchase funds once from approved versioned terms (D06, D13 `purchase:<line>:<component>`, D14.10) | `fund_credit_purchase()`; `credit_purchase_fundings`; `EntitlementDefinition.funding_policy_json.purchase` v1; PostgreSQL funding, purchased-lot and purchased-grant guards | `test_purchase_funds_each_component_once_and_replay_converges`; `test_purchase_rejects_unverified_or_mismatched_evidence[9]`; `test_same_line_cannot_fund_under_a_different_definition`; concurrent funding under three isolation levels |
| D10 cumulative proportional refund, tax/fee excluded, discount-net principal, floor arithmetic, multiple refund objects | `apply_financial_case_effects()`; one immutable `financial_case_lot_evaluations` row per accepted version and lot | `test_partial_refunds_converge_to_the_equivalent_cumulative_refund`; `test_refund_excludes_tax_and_fees_and_uses_discounted_principal`; `test_refund_rounding_floors_in_exact_integers`; `test_two_refund_objects_on_one_line_share_the_cumulative_rule`; `test_full_refund_after_consumption_reverses_only_unused_value` |
| Subscription refund disposition (financial-only and entitlement-reducing review change no credits or entitlements) | Disposition read from the Phase 5.3 current version | `test_subscription_refund_dispositions_preserve_credits_and_entitlements` |
| Dispute opened/pending/won/lost, direct terminal, reopen, hold of unused value only, absorbed shortfall | Source-specific `dispute_hold`, `release`, `dispute_reversal`, `recovery` entries | dispute tests in `test_billing_financial_effects.py`; migrated lifecycle |
| Expiry is not delayed by a hold; expired value is not recreated | Phase 6 expiration consumes held allocations; recovery on an expired lot is recorded as unrestorable with no credit | `test_dispute_hold_does_not_delay_expiry_and_expired_value_is_not_recreated`; `test_won_after_loss_on_expired_lot_records_unrestorable_recovery` |
| Mixed-invoice attribution | `proportional_case_attribution()` is an advisory helper that returns exact splits only and refuses a residual. **The apply path does not call it:** it applies the line allocations stored on the accepted Phase 5.3 version, which the recorder validates only for sum, per-line eligible principal, line kind and cross-case capacity. A caller-supplied multi-line partial split derived by an unapproved remainder rule is therefore accepted (activation blocker; see below) | `test_proportional_attribution_is_exact_or_fails_closed`; `test_partial_dispute_on_mixed_invoice_touches_only_attributed_lines` |
| Recovery bounded by prior reversal for the same case and lot | `financial_case_credit_effects`; PostgreSQL and SQLite recovery bound | `test_cancelled_refund_recovers_exactly_what_it_reversed`; migrated bypass test |
| DB-verifiable source/lot provenance for every case ledger effect (Phase 5.3 deferred requirement) | Evaluation guard (current version, lot funded by the source line); effect guard; deferred final guard on case ledger entries | `test_postgres_migrated_guards_reject_direct_bypass` |
| Idempotency, ordering, and concurrency | Account-first lock order; D13 keys; stale versions apply nothing; unfunded purchase line is retryable (D14.8); the prior version is chosen by the Phase 5.3 acceptance order `(effective_at, received_at)`, never by row time or ID (audit F2); a same-amount refund after its reversal was recovered is refused rather than skipped (audit F1) | duplicate/stale/retry tests; `test_postgres_concurrent_funding_and_case_application_converge`; `test_f1_*`; `test_f2_*` |

Fail-closed paths awaiting decisions: partial reduction of a refunded or
disputed amount, re-refunding an amount whose reversal was recovered,
entitlement-reducing execution, and refunded-value absorption policy.

**Not fail-closed (activation blocker):** the D-1 allocation contract. The
apply path trusts the line allocations on the accepted Phase 5.3 version. It
does not distinguish authoritative processor line-level evidence from
allocations an adapter derived itself, so a derived split using an unapproved
remainder rule would be applied. Phase 9 must not be activated until that
evidence and allocation contract is approved and enforced. Phase 17
acceptance must prove that an adapter cannot record or apply a multi-line
partial allocation except from authoritative processor line evidence or the
approved deterministic rule.

Pre-activation hardening carried forward from the audit: PostgreSQL effect
guards prove provenance but do not reconcile every effect amount to its
evaluation and D10 target (F4); re-applying a case after new lots are funded
can append ledger effects without a new domain event, because the version's
event key is already recorded (F5).

Details are in the Phase 9 audit handoff. Local verification is not acceptance
and does not authorize integration, deployment, or activation.

### Phase 10 implementation record — trials, comps, and internal funding

Status: **implemented locally, inactive; audit remediation round 1 (F1–F5)
and final remediation (R2, F5) complete, awaiting independent
verification.**
Migration `f2b4d6e8a0c3` (revises `e1a3c5b7d9f2`) adds four immutable tables
and narrows the Phase 4 later-authority gate to enterprise contracts (Phase
11). `app/billing_offers.py` has no route, webhook, worker, or scheduler
caller. Phase 3 stays the only ledger, Phase 4 the only entitlement authority,
and Phase 5.4 records every event. No commercial offer, permission holder, or
amount is defined; until Lydia approves offer definitions and staff grants,
every command fails closed.

| Requirement | Component/contract | Regression coverage |
|---|---|---|
| P07/D07: a trial, promotion, or comp is valid only when its approved, versioned offer completely defines eligibility, owner, capabilities, credit amount, start/end, funding source, and redemption limits | `offer_terms()`; `EntitlementDefinition.funding_policy_json.offer` v1 (exact field set; unknown or missing fields fail closed); PostgreSQL redemption guard re-checks every term | `test_unapproved_or_incomplete_offers_fail_closed_without_mutation[11]`; `test_member_attributed_owner_requires_a_policy_decision` |
| T-OFFER-01..04: only approved offers grant entitlement/lots; expiry and owner exact; D13 `offer:<offer_version>:<redemption_id>:<component>` | `redeem_credit_offer()`; `credit_offer_redemptions`, `credit_offer_fundings`; lot, grant, funding and deferred completeness guards; Phase 4 gate replaced by an entitlement-event guard | `test_trial_grants_exact_entitlement_and_lot_once_and_replay_converges`; `test_promotion_with_two_components_and_no_expiry_funds_each_component`; `test_postgres_migrated_guards_reject_direct_bypass` |
| Redemption limits per account (across offer versions) and in total | Sequential per-key indexes, `UNIQUE (offer_key, account, index)` and `UNIQUE (offer_key, total_index)`, guard-verified | `test_per_account_limit_spans_offer_versions_and_total_limit_spans_accounts`; `test_postgres_concurrent_redemptions_respect_limits_and_converge` (3 isolation levels) |
| P08/T-ADMIN, STOP-12/13: admin authority, capabilities, data, and funding are separate; adjustments carry actor, reason, evidence | Comps and internal funding need a named staff user with an explicit, versioned, unrevoked `billing_staff_permission_grants` row plus reason, justification, and evidence. Grants and revocations are recorded only by the provisioning service. Global admin, organization admin, and billing roles are never consulted | `test_comp_requires_explicit_permission_not_admin_or_billing_role`; `test_revoked_or_out_of_interval_permission_authorizes_nothing`; `test_staff_permissions_are_recorded_only_by_the_provisioning_service`; `test_trials_and_promotions_are_redeemed_only_by_the_offer_service[5]` |
| ADR: internal accounts use explicit internal funding, not plan impersonation | `internal` origin funds an `internal` lot; no user, organization, plan, or subscription field is written | `test_internal_funding_is_explicit_credit_not_plan_impersonation` |
| P23/T-OWNER: trial/promo/internal value stays with its account and source; allocation order | Account-owned lots only (member attribution refused); existing `SOURCE_PRIORITY` puts offer lots before purchased credit | `test_offer_value_stays_with_its_account_and_source`; `test_offer_lots_are_allocated_before_purchased_credit_and_stop_at_expiry` |
| Entitlement term: `active -> expired` at term end | `expire_offer_entitlement()` (database time); PostgreSQL guard refuses `active -> expired` before `ends_at` by claimed and database time | `test_offer_entitlement_expires_only_after_its_term`; `test_postgres_f3_only_initial_approval_is_gated_and_later_lifecycle_remains_open` |
| Audit F1: no caller-supplied command time | The commands take no time argument. Recorded timestamps (`redeemed_at`, term start, `revoked_at`, grant recording, entitlement transition times) are the database transaction timestamp (`now()` on PostgreSQL); PostgreSQL guards require `redeemed_at = now()` and `revoked_at = now()`. A retry returns the stored result and original time | `test_f1_callers_cannot_supply_or_backdate_command_time`; `test_retry_after_offer_retirement_returns_the_stored_result`; `test_postgres_f1_database_rejects_caller_supplied_times` |
| Audit R2: authorization at actual current time | The transaction timestamp is a record, not evidence of current authority. Grant expiry and offer retirement are judged with `clock_timestamp()`: in the service after the definition and grant locks are held, in the redemption insert guard after its `FOR SHARE` grant lock, and again in the deferred guard together with revocation. That deferred check normally runs at commit, but only while the constraint stays deferred (known limitation N1, below). Grant start and offer effectiveness are judged at the recorded start, which can only be earlier and so is stricter | `test_postgres_r2_transaction_opened_before_the_deadline_cannot_redeem_after_it[grant, offer]`; `test_postgres_r2_database_guard_refuses_even_if_the_service_used_transaction_start[grant, offer]`; `test_postgres_r2_deadline_between_insert_and_commit_refuses_the_commit[grant, offer]`; `test_postgres_r2_redemption_before_the_deadline_is_valid_and_retries_after_it[grant, offer]` |
| Audit F2: a committed revocation always wins over a later redemption | Redemption and revocation require READ COMMITTED on PostgreSQL (service check and guard); the redemption locks the grant before reading revocations in a separate statement; the revocation guard locks the grant `FOR UPDATE` and the redemption guard `FOR SHARE` | `test_postgres_f2_revocation_committed_during_a_redemption_wins[3 levels]`; `test_postgres_f2_database_refuses_snapshot_isolation_writes[3 levels]`; `test_postgres_f2_concurrent_revocation_and_redemption_have_one_valid_order`; `test_postgres_concurrent_redemptions_respect_limits_and_converge[3 levels]` |
| Audit F3: guard scope | The entitlement-event guard gates only `proposed -> scheduled` (D07 approval); cancellation, reduction, replacement, and disposition expiry stay open | `test_postgres_f3_only_initial_approval_is_gated_and_later_lifecycle_remains_open` |
| Idempotency, replay, atomicity | `offer-redemption:<definition>:<redemption_id>` claim; replay returns the prior result; reuse with different facts or delivery obligations conflicts; a failed event rolls back everything | `test_redemption_identity_reuse_with_different_facts_conflicts`; `test_replay_with_different_delivery_obligations_conflicts`; `test_failed_event_recording_rolls_back_every_effect` |

Deferred, fail-closed, or awaiting decisions: member-attributed offers;
revoking or reducing a comp or internal grant (no negative adjustment command
exists; Phase 9's note that manual adjustments need D11 risk authority
stands); ledger `expiration` entries for offer lots (availability already ends
at `expires_at`); who may hold the two staff permissions and whether a holder
may fund an organization they belong to; customer-facing templates for the new
event types `trial_started`, `promotion_redeemed`, `comp_granted`, and
`internal_funding_granted`.

Enforcement differs by schema (audit F4). The database guards exist only in
migrated schemas. Schemas built with `db.create_all()` have the model CHECK
constraints but no triggers, so there the Phase 4 transition helper could
activate a trial, promotion, comp, or internal instance without a redemption.

The `create_all` entry points are the test fixtures and three manual scripts:
`scripts/init_dev_db.py` (local bootstrap), `create_studio_tables.py`, and
`create_decision_record_tables.py`. The two `create_*_tables.py` scripts call
`db.create_all()` against whatever `DATABASE_URL` is configured. Run against a
database whose migrations are behind, they would create every missing table,
billing tables included, without triggers.

No approved runtime path uses such a schema for billing: every caller of the
helper is an inactive billing module, and production uses Alembic on
PostgreSQL. Closing this gap (D10-10) is a mandatory pre-activation
dependency.

SQLite migrated schemas have the offer-lot and initial-approval guards but
no READ COMMITTED, database-time, or current-time checks.

SQLite itself allows only one writer at a time, but a deferred transaction
reads before it takes the write lock. The service's guarantees therefore
depend on each command's locking:
- Redemption opens `BEGIN IMMEDIATE` through the account lock as its first
  statement, so it holds the write lock from its first read. This applies
  only when the redemption starts the transaction; a caller that already
  opened one keeps SQLite's ordinary deferred locking. While a redemption
  holds the write lock, no revocation can commit.
- `expire_offer_entitlement` reads the redemption's account before
  `_lock_account`, so its transaction has already begun and it does not get
  that up-front lock.
- Grant recording and revocation never take it either; their reads precede
  the write lock. Two revocations of one grant are settled by the unique
  constraint on `grant_id`.

**Known limitation N1 (low severity).** The commit-time re-check
(`phase10_redemption_final`) is a deferred constraint trigger. A caller that
runs `SET CONSTRAINTS ALL IMMEDIATE` (or names that constraint) after
inserting a redemption makes the check run at that moment instead of at
commit. If the grant then expires or the offer retires before the
transaction commits, the commit succeeds. The R2 insert-time and
service-time checks are unaffected; only the "re-check at commit"
protection depends on the constraint staying deferred. The trigger is
unchanged.

Integration contract D10-9: payment adapters and every other caller must
run redemption and revocation in READ COMMITTED, and must not run
`SET CONSTRAINTS ALL IMMEDIATE` or otherwise force early evaluation of the
Phase 10 redemption constraint. Details are in the Phase 10 audit handoff. Local
verification is not acceptance and does not authorize integration,
deployment, or activation.

### Deferred Phase 5.1/5.2 activation gate — conflict evidence integrity

Status: **Deferred — required before inbox activation.** These PostgreSQL
regressions must be implemented and pass before `billing_inbox.record_event()`
is connected to a live event source.

| Test ID | Required assertion |
|---|---|
| T-INBOX-01 | A genuine concurrent duplicate is handled idempotently; it is not misclassified as a conflict or silently lost. |
| T-INBOX-02 | An unexpected `IntegrityError` while recording conflict evidence propagates; it is not suppressed as a harmless duplicate. |
| T-INBOX-03 | `digest_conflict` quarantine is committed only with durable conflict evidence; a failed evidence insert cannot leave a quarantined event without its audit row. |

### Acceptance gates for the target implementation

- Every command produces one authoritative transition or a typed no-op.
- Every read test observes zero writes.
- Every compatibility field equals its projection proof.
- No legacy direct writer remains enabled at final cutover.
- Ledger sums, financial sums, and source/owner partitions reconcile exactly.
- Failure injection at each external/transaction boundary preserves invariants.
- Pricing and capacity policy versions are visible on every authorized AI
  operation; unknown provider/model economics fail closed before execution.

## D18 Phase dependency and cutover map

The original 18 phases are the authoritative implementation sequence because
they expose dependencies and keep changes small/reversible. Phase 2A–2G remain
useful **program gates**, not a competing sequence. This map authorizes nothing.

### Roadmap crosswalk

| Authoritative phase | Deliverable | Phase 2 gate(s) | Required entry/exit evidence |
|---:|---|---|---|
| 1 | ADR and traceability | pre-2A | **Complete:** founder approved this package on 2026-11-09; no code change. |
| 2 | Canonical additive schema | 2A | Organization billing accounts, roles, finance, entitlement, ledger, pricing/capacity versions, inbox/outbox/risk tables; migrations reviewed and reversible. |
| 3 | Ledger primitives | 2A | Append-only constraints, idempotency, zero-floor/concurrency unit tests. |
| 4 | Entitlement and credit periods | 2A | Org-first plans/contracts/UTC anchors and period tests. |
| 5 | Financial transactions and event inbox | 2A | Lines, cumulative cases, ordering/replay tests before funding consumers. |
| 6 | Free and subscription allocations | 2D funding | Period grants use phases 3–5; annual monthly allocation tests pass. |
| 7 | Upgrade, downgrade, and schedules | 2D schedule | Paid/prorated/scheduled precedence and race tests pass. |
| 8 | Seats | 2D seat | Commitment/occupancy and organization permission tests pass. |
| 9 | Refunds, disputes, and purchases | 2D financial/ledger | Cumulative source-specific lifecycle and mixed-line tests pass. |
| 10 | Trials, comps, and internal funding | 2D funding/admin | Approved offer/source/admin authority tests pass. |
| 11 | Enterprise | 2D entitlement | Executed-contract evidence and no-unlimited-default tests pass. |
| 12 | AI reservations and settlements | 2D AI | Pricing/capacity binding, fallback, tools, checkpoint/resume, delivery-based billability, absorbed-usage evidence, and exact settlement tests pass. |
| 13 | Inventory and reconciliation | 2B | Pure projections, all writer/reader inventory, compatibility field proofs. |
| 14 | Backfill | 2B/2C | Evidence-ranked deterministic migration; no unexplained account cut over. |
| 15 | Local rehearsal | 2C | Exact reports, failure injection, downgrade/rollback, rerun no-op. |
| 16 | Shadow verification | 2B/2F | Production-like authorized environment only; projected/legacy comparisons, pricing/capacity telemetry, zero customer impact. |
| 17 | Controlled cutover | 2D then 2E | Command families cut over in dependency order, then readers; explicit separate authorization and rollback gates. |
| 18 | Legacy retirement | 2F/2G | Observation proves zero legacy writes/drift; consumer inventory empty; PR #27 disposition separately decided. |

The old 2A grouping omitted an explicit place for pricing-policy versions and
capacity authorization; these are added to phase 2 foundations and exercised in
phase 12. The old 2D grouping was too broad to be a single safe deployment;
phase 17 must execute it as reviewed, command-family cutovers. Phase 2E reader
cutover occurs only after each writer and projection is proven. Phase 2F spans
shadow evidence and the post-cutover freeze; Phase 2G remains retirement only.

### Cutover ordering rationale

Organization and billing-account identity must precede every entitlement,
financial, ledger, pricing, and capacity record. Financial and event identity
must precede credit grants so one external fact
cannot fund twice. Credit lots must precede AI reservations so consumption has
an owner and source. Pricing and capacity policy versions must precede AI
authorization. Explicit internal/risk permissions must precede removal of admin
shortcuts. Schedules and seats depend on entitlement and financial states.
Readers move only after projections are complete. Legacy writers are retired
only after the projector proves parity; dual writers are never a steady state.

### Phase 2 readiness

Phase 1 received founder architecture approval on 2026-11-09: approved policy
is coherent, all STOP items are mapped, and evidence limitations are stated.
Phase 2 is **not authorized**. Phase 2A/authoritative phases 2–5 may be
considered for separate authorization only after:

1. review of the additive schema/migration/downgrade proposal for the specific
   requested increment;
2. the increment seeds no numerical capacity threshold; later threshold
   proposals must be based on authorized usage/provider evidence rather than
   copied from current defaults; and
3. an implementation plan that preserves PR #27 regression intent without
   modifying or depending on that open PR.

No backfill, shadow use of customer data, production verification, writer
cutover, reader cutover, or retirement is included in that recommendation.
