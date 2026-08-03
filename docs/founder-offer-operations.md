# 300K Limited-Time Offer Operations and Product Contract

## Durable account state

The 300K Limited-Time offer is an `account_entitlements` record keyed to the purchasing
account. It is independent of subscription plan, Stripe subscription status,
request counters, and credit balance. Duplicate webhook delivery cannot create a
second entitlement or promotional credit lot.

The 300,000-credit benefit is a `persistent_credit_grants` lot with an
append-only `persistent_credit_transactions` audit trail. Plan changes and
monthly resets do not erase the personal promotional balance or entitlement.

Consumption order is:

1. monthly plan credits and normal expiring top-ups;
2. persistent 300K Limited-Time credits;
3. the existing small soft-stop grace, only after paid balances are empty.

Refunds and chargebacks tied to the one-time payment reverse the unused persistent
balance and retain the entitlement/grant records for audit. The entitlement is
not silently deleted. Account deletion follows the existing user cascade and is
the only account-level destructive action.

## Limits and limit messages

While 300K Limited-Time credits remain, the account receives 100 Claude-powered requests
per hour and 300 per day. When the persistent balance reaches zero, the existing
active-plan limits apply automatically. The same shared account counters cover
chat, score-next, score-batch, and AI execution-plan generation. Rate-limit
responses must include `Retry-After`; Thinking Power exhaustion includes the
monthly reset timestamp.

Every plan, including the 300K Limited-Time offer, supports up to 30 peer projects in one comparison
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
| The 300K Limited-Time offer (300,000 persistent credits) | ~750–1,200 typical project evaluations over the life of the credit balance; available until used |

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

- `PRICE_ID_300K_LIMITED_TIME`: one-time $999 Stripe Price. The product must not be recurring.
- Webhook secret and delivery for Checkout completion, refund, and dispute events.
- `invoice.paid` must be among the delivered webhook events. A discounted purchase settles
  as an invoice, not as the checkout's own payment intent, and that event is the backstop
  if the buyer closes the tab before the browser confirms.
- Redis-backed `RATELIMIT_STORAGE_URI` in production.
- Apply the database migration and run the scorecard backfill before traffic.

## Refund policy

We resolve the issue, or we refund it. There is no third outcome.

A refund is owed when a Covered Technical Failure is reported inside the
30-day window and we do not correct it within ten business days of having what
we need to investigate. Anything else — dissatisfaction, a disagreement with a
score, a changed situation, simply not using the credits — is not refundable,
and the offer is sold on that basis.

**Partial use does not change the answer.** A buyer who has spent part of the
300,000 credits is still owed a refund if we fail to fix a qualifying failure;
having spent them is never on its own a reason to refund. Refund the full
amount paid to the original payment method, then reverse the entitlement with
`reverse_limited_time_300k_credits`, which reverses the unused lot and drops
the standalone access that came with the offer.

Because this is settled through Stripe, refund the invoice or payment intent
recorded on the grant (`stripe_invoice_id` / `stripe_payment_intent_id` in the
grant metadata), so Stripe and our records agree.

Stated for buyers in the Technical Assurance section of
`/limited-time/terms-and-conditions` and, in short form, under Refunds in
`/pages/terms`. Keep all three in agreement if any of them changes.

## Testing the offer in production with a promo code

The point is to walk the real live-mode purchase without moving real money. A
100%-off promotion code does that: Stripe settles the whole $999 on an invoice,
records the redemption, and the credits are granted with no card charged.

In Stripe (live mode):

1. Create a coupon at **100% off**, duration **once**.
2. Leave it applying to **all products**, or explicitly add the 300K product to it.
   A coupon restricted to the subscription prices is the single most common reason a
   code "works" but discounts nothing — Stripe attaches it and takes nothing off.
3. Create a **promotion code** on that coupon (the customer-facing code — a coupon
   alone cannot be typed at checkout), with **max redemptions** set low, e.g. 3.
4. Confirm it before touching checkout:
   `PYTHONPATH=. ./venv/bin/python scripts/check_300k_promo_code.py YOURCODE`

Then buy the offer as a normal buyer would: open the campaign page, create or sign
into an account, accept both acknowledgements, continue to payment, enter the code,
and press Apply. A fully covering code replaces the card form with a confirmation
and grants the credits immediately. A partial code re-prices the payment through the
invoice Stripe priced, and the card fields re-mount against it.

Afterwards, in Stripe: the promotion code shows a redemption, and the invoice shows
`checkout_type=300k_limited_time` with the code in its metadata. In Jaspen: the
account holds the 300K entitlement and the credit grant.

Archive the promo code once testing is done — an active 100%-off code is a live
$999 giveaway to anyone who guesses it.

Remaining decisions: whether a partial refund should reverse credits pro rata instead of reversing the unused lot, and whether
the provisional per-plan portfolio-view ladder should change after scale tests.
