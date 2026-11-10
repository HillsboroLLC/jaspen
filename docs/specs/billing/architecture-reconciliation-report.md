# Phase 1 Architecture Reconciliation Report

Status: **Founder-approved architecture; no implementation or cutover authorized**

Date: 2026-11-09

## Executive conclusion

The Phase 1 package is coherent after reconciliation. It now specifies one
organization-first customer model, one organization billing account per
commercial relationship, one append-only credit ledger, separate financial and
entitlement authorities, effective-dated pricing, and a credit-independent
short-term capacity authority. All STOP-01 through STOP-25 have approved policy
and a documented resolution. None should be read as implemented or authorized
for cutover.

Founder approval was recorded on 2026-11-09. The additive-foundation portion of
Phase 2 can be considered only through later, explicit phase authorization and
the reviewed reversible proposal. No migration, backfill, production
verification, or cutover is authorized.

## What was already correct

- The separation of financial facts, entitlements, credit lots/entries, AI
  operations, projections, risk restrictions, and communications.
- Append-only ledger authority, pure reads, hard nonnegative balances,
  reservation-before-execution, exact release/settlement, and idempotent replay.
- Deterministic UTC periods, annual monthly allocations, no recurring rollover,
  payment-gated upgrades, schedule precedence, and preservation of funded
  benefits during payment failure.
- Source-specific proportional refunds; reversible dispute holds; mixed-invoice
  line attribution; auditable recovery.
- Seat commitment versus occupancy; Enterprise contract evidence; admin
  authority independent from plan/funding.
- Evidence-ranked migration, exact conservation, quarantine of unexplained
  discrepancies, compatibility sunset conditions, and preservation of PR #27's
  regression intent.

## Corrections made from founder decisions

1. Removed the proposed personal-versus-organization billing split. Every
   customer is now an organization, including one-member accounts. Member-only
   or member-attributed value remains inside the organization billing account.
2. Added immutable pricing-policy versions, customer-impact classification,
   advance notice evidence, effective dates, and authorization-time binding.
3. Added provider-independent capacity authorization separate from credits,
   including organization fairness, member anti-monopoly controls, concurrency,
   tier preference, provider pressure, abuse/runaway protection, and typed
   next-available outcomes. No numeric limits were adopted.
4. Specified **Usage & Billing**, ledger-synchronized overall/session usage,
   distinct payment/credit-refresh/term fields, the retained top-right
   **BALANCE**, and one configurable 20% low-credit warning per period.
5. Reconciled the 18 phases with Phase 2A–2G. The 18 phases are authoritative;
   A–G are program gates.
6. Expanded each STOP item with policy, resolution, evidence, remaining work,
   tests, dependencies, and decision status.

## Existing implementation to retain

- AI operation identity, request fingerprints, durable successful-result replay,
  validation-before-settlement intent, provider-attempt audit, and absorbed
  failed-attempt reporting in `ai_runtime.py`, `ai_audit.py`, and governed routes.
- Claude/Gemini routing and retryable-error classification, subject to one
  capacity/pricing authorization across fallback.
- Production Redis requirement for shared rate-limit counters and the property
  that a limiter denial occurs before provider work or credit deduction.
- Purchase/offer idempotency patterns, persistent source records, refund audit
  history, payment receipt identity, and existing seat/annual interval tests.
- Existing **BALANCE** affordance, session persistence, and useful usage/admin
  telemetry, once backed by pure authoritative projections.

## Existing implementation requiring correction

- Read-triggered credit initialization/reset and organization plan sync.
- Multiple mutable balance authorities and transient reservation allocations.
- User-owned Stripe identity and active-organization-dependent billing context.
- Soft negative grace, dunning credit caps, annual full-reset paths, and
  schedule authority in Stripe metadata.
- Non-cumulative refunds/disputes and direct admin balance writes.
- Hard-coded/manual pricing rates without effective dates or notification
  evidence; split legacy versus shadow credit-conversion pathways.
- Per-user request quotas that multiply across organization members; absence of
  organization-wide capacity, unified concurrency, queue priority, and
  provider-pressure policy.
- A hard-coded 10% low-credit threshold and per-session warning behavior rather
  than the approved configurable 20% once per funded period.
- 429 copy suggesting additional credits can bypass capacity.

## Risks and evidence limits

- Production pricing modes, model IDs, multiplier, budgets, provider tier, and
  rate-limit configuration cannot be proven from repository evidence and were
  not accessed.
- Realized margin cannot be inferred from catalog formulas. It depends on actual
  operation mix, retries, fallback, tools, subsidies, provider invoices, and
  revenue/fees.
- Current preflight estimation does not prove worst-case reservation coverage.
- The current local AI-governance suite is not wholly green: two provider
  refusal/timeout classification tests failed during this review. The pricing
  and capacity report records exact results; no code fix was authorized.
- Numerical capacity policy needs production-like usage distributions, provider
  quotas/latency, concurrency simulations, abuse scenarios, and tier economics.
- Migration cannot proceed until every account maps to an organization billing
  account and unresolved owner/source/contract evidence is reviewed.

## Genuine founder decisions still needed

None remain for the approved architecture. Later approvals must set numeric
capacity/concurrency/queue thresholds and any exact notification wording,
channels, lead time, or terminal dunning timing. Those are deliberately not
invented here and are not prerequisites to approve the documented boundaries.

## Recommended sequence

Use the 18 phases in
[traceability-and-cutover.md](traceability-and-cutover.md#d18-phase-dependency-and-cutover-map).
Authorize phases independently, require executable exit evidence, and never
bundle schema, backfill, writer cutover, reader cutover, and retirement.

## Approval statement

Founder approval covers the target architecture and implementation sequence
only. It does not certify current implementation, approve numeric
capacity limits, authorize production access, authorize Phase 2, merge PR #27,
or authorize customer/data migration.
