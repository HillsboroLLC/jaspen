# Jaspen AI Routing and Credit Policy v1

Status: development-only; both policies default to `shadow`.

## Policy

- Claude is primary. Gemini is the only core failover provider.
- Customer plan does not determine model capability.
- Jaspen selects a route from the operation type, requested work, consequence,
  ambiguity, context size, attachments, alternatives, and validation failures.
- Public credits map at 3,600 credits per provider dollar. The existing ledger
  retains 1,000 internal units per displayed credit.
- A customer-visible operation is settled once from the successful result's
  provider cost. Failed attempts and internal support calls are Jaspen costs.
- Free, test, admin/unlimited, promotional, fully-comped, anonymous public
  intake, and internal use is classified explicitly as subsidized. It is not
  treated as revenue-backed margin.
- Purchased credit packs are persistent, non-expiring lots. Monthly resets do
  not remove them; refunds and disputes reverse only unused value and retain
  the transaction history.

## Automatic routes

| Class | Primary | Fallback |
| --- | --- | --- |
| Routine | Claude Haiku | Gemini Flash |
| Standard judgment | Claude Sonnet | Gemini Pro, then Gemini Flash |
| Structured/consequential | Claude Sonnet | Gemini Pro, then Gemini Flash |
| Exceptional depth | Claude Opus | Claude Sonnet, then Gemini Pro |

Opus is reserved for multiple depth signals; prompt length alone is not enough.

## Audit boundary

`ai_operations` stores the customer-visible operation and its one settlement.
`ai_provider_attempts` stores every known provider attempt. Each operation keeps
the route class/reason, selected and final provider/model, failover/escalation,
successful and total known cost, projected and charged credits, subsidized
status, and router/policy versions.

If a failed provider attempt returns usage, the ledger records its actual
cost. If it does not, the gateway records a conservative token/cost estimate,
labels the estimate method, and marks that cost as Jaspen-absorbed.

Customer-visible operations accept `X-Jaspen-Idempotency-Key`. The shared
runtime claims a namespaced operation before generation and replays its stored
successful result on retry. The tool-capable streaming conversation boundary
is the documented exception to the generic executor: it uses the same router,
provider adapters, pricing, settlement, and audit ledger, but keeps a bounded
durable response cache in the thread because its tool loop must stream partial
events. In both paths a completed retry does not generate or charge again.
Anonymous public intake is non-billable and deliberately does not retain a
durable response replay; this keeps visitor chat content out of the operation
result cache.

## Gateway coverage

- Authenticated chat, reports, insights, connector generation, scorecards,
  scorecard assistants, portfolio analysis, score batches, and execution-plan
  generation use the shared governed runtime or the governed streaming
  conversation boundary.
- Anonymous public-intake chat uses the system runtime and is classified as
  `public_intake`; it never debits a customer.
- Feedback digests and user-memory extraction use the system runtime and are
  classified as `internal`.
- Decision-impact narrative model generation is retired. The current
  deterministic narrative remains authoritative; the dormant model seam is
  retained only for test compatibility and returns no model content.
- Legacy direct-Anthropic fallbacks have been removed. A deterministic
  heuristic response may be used when no provider is configured or all routes
  fail; it is explicitly marked `degraded` and is not a hidden provider call.

## Runtime controls

- `JASPEN_AI_ROUTER_MODE=shadow|active|off`
- `JASPEN_CREDIT_POLICY_MODE=shadow|active|off`

Default is `shadow`. In shadow mode, the legacy route and legacy charge remain
customer-visible while the proposed route and 3,600-credit charge are recorded.
The two controls must be activated separately after production-like shadow
validation; changing one must not implicitly change the other.

## Promotion gates

1. Apply migration `a7c9e2f4b610` to a recent PostgreSQL production clone.
2. Confirm row counts and numeric balances are unchanged.
3. Run representative logged-in operations in shadow with real Claude/Gemini
   credentials and verify the operation/attempt ledger.
4. Compare quality, latency, failover, and projected charges by route class.
5. Confirm every configured model has a conservative provider-price entry.
6. Activate the router first while leaving credit policy in shadow.
7. Observe quality/failover; then activate the credit policy separately.
8. Keep Pluto/Orbit/Titan visible until the replacement UI is validated.

Do not promote by toggling both policies and migrating the database in one step.

## Margin interpretation

The 3,600-credit conversion guarantees the intended direct-cost floor for the
successful customer-visible completion at current catalog economics. It cannot
guarantee that every individual request retains a 90% all-in margin after an
expensive failed provider attempt because the customer is charged only once.
The ledger therefore reports successful cost and Jaspen-absorbed attempt cost
separately. Production activation requires observing the failure distribution
in shadow mode and applying operational retry/circuit-breaker limits if the
aggregate paid-workflow margin falls below target.
