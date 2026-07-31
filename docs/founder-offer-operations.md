# Founder Offer Operations and Product Contract

## Durable account state

Founder status is an `account_entitlements` record keyed to the purchasing
account. It is independent of subscription plan, Stripe subscription status,
request counters, and credit balance. Duplicate webhook delivery cannot create a
second entitlement or Founder credit lot.

The 300,000-credit benefit is a `persistent_credit_grants` lot with an
append-only `persistent_credit_transactions` audit trail. A normal Essential
renewal resets only monthly credits. Downgrade, cancellation, failed payment,
and monthly reset do not erase the persistent balance or Founder identity.

Consumption order is:

1. monthly plan credits and normal expiring top-ups;
2. persistent Founder credits;
3. the existing small soft-stop grace, only after paid balances are empty.

Refunds and chargebacks tied to the Founder invoice reverse the unused persistent
balance and retain the entitlement/grant records for audit. Founder identity is
not silently deleted. Account deletion follows the existing user cascade and is
the only account-level destructive action.

## Limits and limit messages

While Founder credits remain, the account receives 100 Claude-powered requests
per hour and 300 per day. When the persistent balance reaches zero, the existing
active-plan limits apply automatically. The same shared account counters cover
chat, score-next, score-batch, and AI execution-plan generation. Rate-limit
responses must include `Retry-After`; Thinking Power exhaustion includes the
monthly reset timestamp.

Every plan, including Founder, supports up to 30 peer projects in one comparison
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

These estimates are ranges, not guarantees. A “project evaluation” assumes
framing/chat, rubric work, one scored scorecard, review, and one initial AI
execution plan. Code-based planning assumptions are roughly 145 credits for an
efficient complete-input project, 305 for typical moderate questioning, and 829
for a heavy attachment/revision workflow. Real production `usage_events` should
replace these assumptions.

| Allowance | Approximate project evaluations |
|---|---:|
| Free (300) | ~0–2 |
| Starter (1,000) | ~1–6 |
| Essential (7,000) | ~8–48 |
| Team (29,000) | ~35–200 |
| Business (80,000) | ~95–550 |
| Founder persistent 300,000 | ~360–2,060 |

Suitable external wording: “Approximately ~360–2,060 project evaluations from
the Founder balance, depending on input completeness, supporting documentation,
model selection, analysis depth, and revisions.” Never describe Thinking Power
credits as tokens and never promise an exact project count.

## Margin decision note

Formula in code:

`debit percentage = raw provider cost × margin multiplier ÷ plan budget`

The adjacent budget comment says the budget is “before margin,” which by itself
could imply `raw cost ÷ budget`. Repository history resolves intent: commit
`2149e33a` explicitly introduced provider cost multiplied by margin before debit
and described this as preserving margin. The formula remains unchanged; the
contradictory comment must be treated as documentation debt.

At the default Essential values (budget $13, multiplier 3×):

| Interpretation | Raw provider value of 300,000 credits | Margin at $450 | Margin at $499 |
|---|---:|---:|---:|
| Code/history: cost × 3 before debit | $185.71 | 58.7% | 62.8% |
| Comment-only: raw cost ÷ budget | $557.14 | -23.8% | -11.7% |

The included $39 Essential month lowers the first-cycle headline margins to
about 50.0% at $450 and 55.0% at $499 before payment fees and other operating
costs. Metered scorecards and execution plans now consume the purchased balance
instead of creating untracked cost; the ranges above include provisional 15- and
48-credit equivalents for those operations.

Production must confirm `JASPEN_MARGIN_MULTIPLIER`, all `JASPEN_BUDGET_*`
values, Anthropic model routing/prices, and real usage before campaign claims.

## Stripe and environment checklist

- `PRICE_ID_THINKING_POWER_300K`: one-time Founder offer price ($450 or $499,
  product-owner decision required).
- Essential monthly and annual price ids.
- First-month promotion code: active, duration `once`, scoped only to the
  Essential recurring product so it cannot discount the one-time line.
- Webhook secret and delivery for invoice success, refund, and dispute events.
- Redis-backed `RATELIMIT_STORAGE_URI` in production.
- Apply the database migration and run the scorecard backfill before traffic.

Remaining decisions: final $450 versus $499 price, whether a partial refund
should reverse credits pro rata instead of reversing the unused lot, and whether
the provisional per-plan portfolio-view ladder should change after scale tests.
