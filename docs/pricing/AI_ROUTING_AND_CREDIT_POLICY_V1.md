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
- Free, test, admin/unlimited, and fully-comped use is marked subsidized. It is
  not treated as revenue-backed margin.
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

If a provider fails before returning token usage, its cost is recorded as
unknown—not zero—and is marked as Jaspen-absorbed.

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
