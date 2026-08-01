# The Jaspen Advantage Operations and Product Contract

## Durable account state

The Jaspen Advantage is an `account_entitlements` record keyed to the purchasing
account. It is independent of subscription plan, Stripe subscription status,
request counters, and credit balance. Duplicate webhook delivery cannot create a
second entitlement or promotional credit lot.

The 300,000-credit benefit is a `persistent_credit_grants` lot with an
append-only `persistent_credit_transactions` audit trail. Plan changes and
monthly resets do not erase the personal promotional balance or entitlement.

Consumption order is:

1. monthly plan credits and normal expiring top-ups;
2. persistent Jaspen Advantage credits;
3. the existing small soft-stop grace, only after paid balances are empty.

Refunds and chargebacks tied to the one-time payment reverse the unused persistent
balance and retain the entitlement/grant records for audit. The entitlement is
not silently deleted. Account deletion follows the existing user cascade and is
the only account-level destructive action.

## Limits and limit messages

While Jaspen Advantage credits remain, the account receives 100 Claude-powered requests
per hour and 300 per day. When the persistent balance reaches zero, the existing
active-plan limits apply automatically. The same shared account counters cover
chat, score-next, score-batch, and AI execution-plan generation. Rate-limit
responses must include `Retry-After`; Thinking Power exhaustion includes the
monthly reset timestamp.

Every plan, including The Jaspen Advantage, supports up to 30 peer projects in one comparison
session. This is a comparison-session creation guard, not an account storage or
retention cap. Reaching the limit is checked before Claude is invoked. The
response lists requested, generated, and persisted counts plus every name not
persisted, keeps all existing scorecards accessible, and directs the user to a
new session.

The 30-project launch limit reflects the measured 20/30/40/50-card validation of
payload, query, browser rendering, and trade-off readability. Revalidate before
raising it.

## Retention and peer scorecards

`scorecards` is the authoritative additive peer store. Every row has a stable id,
owner, optional organization, thread/session, project name, rubric, evidence,
score, assumptions, recommendation, execution-plan reference, searchable
metadata, full payload, and timestamps. New scoring dual-writes the legacy
session/scenario shape for compatibility. Reads merge peer rows with legacy data
and honor archived tombstones.

No scorecard is automatically a baseline. Creation order has no comparison
meaning. Deleting the first, middle, or final scorecard archives only that card;
the session remains. Explicit session deletion is a separate operation and
archives its scorecards. Downgrade, cancellation, renewal, credit depletion, and
creation-limit changes never delete retained scorecards.

Run the idempotent backfill before enabling peer-first reads in production:

```bash
cd backend
PYTHONPATH=. ./venv/bin/python scripts/backfill_peer_scorecards.py
```

## Thinking Power metering

Thinking Power is charged only for actual provider work. Claude chat,
score-next, score-batch, and AI execution plans reserve before invocation and
settle against reported input/output usage. `usage_events` records account,
user, endpoint, operation, provider/model, input/output tokens, raw cost,
reserved/settled credits, related thread/scorecard, success/failure, and error
code. A failed call releases unused reservation; reported provider usage is still
settled because cost was incurred.

Deterministic PDF, PowerPoint, Excel, Word, and CSV generation; downloads;
database retrieval; rendering; and ordinary Jira synchronization are not charged.

## Provisional project-capacity estimates

These estimates are ranges, not guarantees. A “project evaluation” assumes an
end-to-end workflow from framing through a reviewed recommendation and initial
execution plan. Actual usage varies based on model selection, input completeness,
attachments, analysis depth, revisions, and follow-up. Production telemetry
should refine these provisional ranges over time.

| Allowance | Approximate project evaluations |
|---|---:|
| Free (300) | ~1 focused evaluation with complete inputs |
| Starter (1,000) | ~3–4 typical project evaluations |
| Essential (7,000) | ~17–29 typical project evaluations |
| Team (29,000 shared credits) | ~57–96 typical project evaluations across the shared allowance |
| Business (80,000 shared credits) | ~133–222 typical project evaluations across the shared allowance |
| The Jaspen Advantage (300,000 persistent credits) | ~750–1,200 typical project evaluations over the life of the credit balance; available until used |

Suitable external wording: “300,000 non-expiring usage credits support an estimated
750–1,200 typical project evaluations over the life of the credit balance.” Follow it with the variability explanation above. Never describe
Thinking Power credits as tokens and never promise an exact project count.

## Margin decision note

Formula in code:

`debit percentage = raw provider cost × margin multiplier ÷ plan budget`

The adjacent budget comment says the budget is “before margin,” which by itself
could imply `raw cost ÷ budget`. Repository history resolves intent: commit
`2149e33a` explicitly introduced provider cost multiplied by margin before debit
and described this as preserving margin. The formula remains unchanged; the
contradictory comment must be treated as documentation debt.

At the default Essential metering values (budget $13, multiplier 3×):

| Interpretation | Raw provider value of 300,000 credits | Margin at $999 |
|---|---:|---:|
| Code/history: cost × 3 before debit | $185.71 | 81.4% |
| Comment-only: raw cost ÷ budget | $557.14 | 44.2% |

No Essential month or recurring subscription is bundled. Metered scorecards and execution plans consume the purchased balance
instead of creating untracked cost; the ranges above include provisional 15- and
48-credit equivalents for those operations.

Production must confirm `JASPEN_MARGIN_MULTIPLIER`, all `JASPEN_BUDGET_*`
values, Anthropic model routing/prices, and real usage before campaign claims.

## Stripe and environment checklist

- `PRICE_ID_JASPEN_ADVANTAGE`: one-time $999 Stripe Price. The product must not be recurring.
- Webhook secret and delivery for Checkout completion, refund, and dispute events.
- Redis-backed `RATELIMIT_STORAGE_URI` in production.
- Apply the database migration and run the scorecard backfill before traffic.

Remaining decisions: whether a partial refund should reverse credits pro rata instead of reversing the unused lot, and whether
the provisional per-plan portfolio-view ladder should change after scale tests.
