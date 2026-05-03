# Stripe Go-Live Checklist

This checklist is intentionally **configuration-only**. No live keys or live Price IDs are included here.

## 1. Products and Prices to Create in Stripe

Create these products/prices in Stripe Dashboard first.

- Free: No Stripe recurring price required (internal plan only).
- Pro (maps to Jaspen `essential`): Monthly recurring subscription price. Env target: `PRICE_ID_ESSENTIAL`.
- Team: Monthly recurring subscription price. Env target: `PRICE_ID_TEAM` (or legacy `PRICE_ID_GROWTH`).
- Enterprise: Monthly recurring subscription price (if billed via Stripe subscription). Env target: `PRICE_ID_ENTERPRISE` (or legacy `PRICE_ID_TRANSFORM_BASIC`).
- Overage Packs: One-time prices for credit packs using `PRICE_ID_OVERAGE_1000`, `PRICE_ID_OVERAGE_5000`, and `PRICE_ID_OVERAGE_20000`.

## 2. Required Environment Variables

Set these before production cutover.

- `STRIPE_SECRET_KEY` (must be `sk_live_...` in production)
- `STRIPE_WEBHOOK_SECRET`
- `PRICE_ID_ESSENTIAL`
- `PRICE_ID_OVERAGE_1000`
- `PRICE_ID_OVERAGE_5000`
- `PRICE_ID_OVERAGE_20000`

Recommended for sales-led billing:

- `PRICE_ID_TEAM` (or `PRICE_ID_GROWTH`)
- `PRICE_ID_ENTERPRISE` (or `PRICE_ID_TRANSFORM_BASIC`)

## 3. Required Webhook Events

Configure Stripe webhook endpoint to include at minimum:

- `checkout.session.completed`
- `invoice.payment_succeeded`
- `invoice.payment_failed`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `customer.subscription.paused`
- `charge.refunded`

## 4. Required Webhook Secret

- Copy webhook signing secret from Stripe endpoint configuration.
- Set it as `STRIPE_WEBHOOK_SECRET`.
- Verify signature validation is passing in backend logs.

## 5. Test Checkout Flow (Before Live)

Use Stripe test mode first:

1. Sign in as a test user.
2. Start checkout for Pro/Essential.
3. Complete checkout with Stripe test card.
4. Confirm app updates user plan and credits.
5. Confirm webhook event recorded and marked processed.

## 6. Test Subscription Upgrade/Downgrade Flow

1. Upgrade Free -> Pro.
2. Upgrade Pro -> Team (if self-serve path enabled).
3. Downgrade Pro/Team -> Free.
4. Confirm plan key, stripe subscription ID, and credits behavior after each change.

## 7. Test Credit Allocation After Payment

1. Buy each overage pack in test mode.
2. Confirm `credits_remaining` increases correctly.
3. Confirm duplicate webhook replay does **not** double-apply credits.

## 8. Test Failed Payment Behavior

1. Trigger `invoice.payment_failed` in Stripe test tools.
2. Confirm backend logs warning and webhook is marked processed.
3. Confirm account state behavior matches business policy.

## 9. Pre-Go-Live Final Steps

1. Replace test keys with live keys in production env.
2. Populate live Price IDs for all required plans/packs.
3. Confirm `STRIPE_SECRET_KEY` starts with `sk_live_`.
4. Redeploy backend.
5. Run smoke tests on checkout + webhook + credits.
6. Monitor logs for first 24 hours for billing/webhook anomalies.
