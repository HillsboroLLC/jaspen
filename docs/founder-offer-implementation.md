# Founder Offer Infrastructure Implementation

> Started 2026-07-31 on `feature/founder-offer-infrastructure` from
> `main` at `d393cc56`. This note records the implementation boundary and
> decisions made from the validation and peer-scorecard audits.

## Starting state

- The checkout work existed only as uncommitted local changes. It created a
  recurring Essential subscription plus a one-time pack, but granted the
  300,000 credits into a monthly bucket that renewal clears.
- Batch scoring generated before checking capacity and swallowed persistence
  failures. The first generated card was stored as a privileged baseline;
  deleting it could delete the entire session.
- The Scores page, portfolio agent, and some exports did not consume the same
  complete scorecard collection.
- Batch scoring, score-next, and AI-WBS invoked Claude without consistent
  reservation, settlement, usage telemetry, or account-level rate limiting.

## Implementation decisions

1. Use dedicated additive tables for account entitlements, persistent credit
   grants/transactions, and standalone peer scorecards. Session/scenario data
   remains a legacy compatibility source during dual-write and backfill.
2. Consume expiring monthly plan credits before persistent Founder credits.
   Renewal, downgrade, cancellation, and failed payment may change the monthly
   allowance but do not erase the persistent balance or Founder identity.
3. Treat capacity as a pre-generation view constraint. Limits gate new creation
   only; they never delete or hide retained work.
4. Meter only actual provider invocations. Deterministic exports, retrieval,
   rendering, and synchronization remain free.
5. Keep the current Thinking Power conversion formula. Repository history for
   commit `2149e33a` explicitly says provider cost is multiplied by margin before
   debit. The contradictory “before margin” budget comment is documentation
   debt; no commercial formula is changed in this branch.
6. Use the flat peer shape from
   `decision_records.py::_collect_peer_scorecards` as the compatibility contract.

## Initial safety limits

- Founder-active request windows: 100/hour and 300/day while persistent Founder
  credits remain. At zero persistent balance, active-plan limits apply
  automatically. These counters are account scoped and shared across Claude
  endpoints.
- Initial portfolio view limit: 40 peer scorecards. This follows the audit's
  supported candidate and is enforced before generation. It is not an account
  retention limit.

The 20/30/40/50 performance measurements remain a release-validation task; the
40-card limit must not be raised without that evidence.
