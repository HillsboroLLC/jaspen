# Codex brief — admin analytics reports plan membership as revenue

## Symptom

The master analytics dashboard (`/api/v1/admin/master/analytics`, rendered by
`frontend/src/jaspenInterface/Admin/MasterAnalytics.jsx`) shows **6 Completed
Purchases** and **$138 MRR** on an account where the only "sales" were $0
coupon redemptions used for testing.

$138 is exactly `3 × $39 + 3 × $7`. Both numbers are computed from how many
accounts are sitting on a paid plan, multiplied by hardcoded prices. **Nothing
in either calculation ever looks at a payment.**

## Root cause (confirmed by read-only trace)

`backend/app/routes/admin.py:671–687`, inside `master_analytics()`:

```python
671  active_paid_statuses = {"active", "trialing"}
672  paid_plans = {"starter", "essential", "team", "business"}
673  plan_mrr = {"starter": 7, "essential": 39, "team": 0, "business": 0}
679  paid_users = User.query.filter(func.lower(User.subscription_plan).in_(paid_plans)).all()
680  completed_purchases = sum(
681      1 for user in paid_users
682      if str(user.subscription_status or "").lower() in active_paid_statuses
683      or str(user.subscription_plan or "").lower() in {"starter", "essential"}
684  )
687  mrr = sum(plan_mrr.get(str(user.subscription_plan or "").lower(), 0) for user in paid_users)
```

Five separate defects, in severity order:

1. **Neither metric is derived from money.** A plan set by coupon, by hand, or
   by an internal grant is indistinguishable from a paid one.
2. **`completed_purchases` ignores status for starter/essential.** The `or` on
   line 683 is unconditionally true for those two plans, so a **canceled,
   past_due, or unpaid** starter/essential account still counts as a completed
   purchase. The status check on line 682 only ever filters team/business.
3. **`mrr` applies no status filter at all** (line 687 iterates all
   `paid_users`). Canceled and past_due subscriptions keep contributing MRR
   until the plan field itself changes.
4. **Team and business are priced at $0** (line 673) while the real catalog
   has them at $129 and $299 (`backend/app/billing_config.py:67,84`). Every
   team account contributes nothing to MRR. The hardcoded $7/$39 also
   duplicates `monthly_price_usd` in that catalog and will drift from it, and
   both ignore `annual_monthly_price_usd` ($6/$32/$107/$249), so an annual
   subscriber is over-counted. Team and business are `price_model: per_seat`
   with `included_seats` and `additional_seat_price`, so a single flat number
   cannot be right for them at all.
5. **Real one-time sales are invisible.** `grant_limited_time_300k_offer`
   (`backend/app/founder_entitlements.py:54`) never touches
   `subscription_plan`, so a **$999 300K Limited-Time purchase does not appear
   in Completed Purchases**. The dashboard counts comped accounts as purchases
   and omits actual paid ones.

## What is missing

There is **no local record of money received.** Confirmed:

- No payments/invoices/charges table. `StripeWebhookEvent`
  (`backend/app/models.py:1126`) stores only `stripe_event_id`, `event_type`,
  `processed`, and timestamps — no amount.
- The in-app payment history (`billing.py:917 list_invoices`) reads
  `stripe.Invoice.list` **live per request** and is per-user, so it cannot
  serve an aggregate dashboard.
- The only local financial rows are the 300K credit grants
  (`PersistentCreditGrant`), which record credits, not dollars.

Two ways to close that gap: query Stripe when the dashboard loads, or record
amounts as webhooks arrive. **Record on webhook.** A dashboard query would be
slow, rate-limited, and would still not distinguish a $0 redemption from an
absent one — and `amount_paid` is `0` on a fully-discounted invoice, which is
exactly the signal we want to keep rather than average away.

---

# Implementation

Backend first; the UI change in step 6 is cosmetic once the data is right.

## 1. Add a `payments` table

New model in `backend/app/models.py`, alongside `StripeWebhookEvent`:

```python
class Payment(db.Model):
    """Money actually received, as reported by Stripe. One row per settled
    Stripe object. Amounts are in cents to mirror Stripe exactly — never
    floats."""
    __tablename__ = 'payments'

    id = db.Column(db.String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = db.Column(db.String(36), db.ForeignKey('users.id', ondelete='SET NULL'), nullable=True, index=True)
    organization_id = db.Column(db.String(36), nullable=True, index=True)

    # Idempotency: the Stripe object id (in_… or pi_…). Unique so a webhook
    # retry or a replayed event cannot double-count revenue.
    external_reference = db.Column(db.String(255), nullable=False, unique=True, index=True)
    source = db.Column(db.String(40), nullable=False, index=True)   # 'subscription_invoice' | 'limited_time_300k' | 'credit_pack'

    amount_paid_cents = db.Column(db.Integer, nullable=False, default=0)   # net of discount — 0 for a fully-comped invoice
    amount_due_cents = db.Column(db.Integer, nullable=False, default=0)    # list price before discount
    discount_cents = db.Column(db.Integer, nullable=False, default=0)
    currency = db.Column(db.String(8), nullable=False, default='usd')

    # Set when the payment was fully discounted, so $0 redemptions can be
    # counted as redemptions instead of disappearing into a revenue average.
    is_comped = db.Column(db.Boolean, nullable=False, default=False, index=True)
    promotion_code = db.Column(db.String(120), nullable=True)

    plan_key = db.Column(db.String(40), nullable=True, index=True)
    billing_interval = db.Column(db.String(10), nullable=True)   # 'month' | 'year' | None for one-time
    stripe_subscription_id = db.Column(db.String(255), nullable=True, index=True)
    paid_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
```

**Migration parent:** the revision graph has a **single head**, confirmed via
Alembic's own `ScriptDirectory.get_heads()`:

```
374bcfa9f423  — Rename the Jaspen Advantage entitlement/credit source key to 300K Limited-Time
```

Set `down_revision = "374bcfa9f423"`. No merge revision is needed. Re-run the
check before writing the file in case another branch has landed since:

```bash
cd backend && venv/bin/python -c "from alembic.config import Config; from alembic.script import ScriptDirectory; c=Config('alembic.ini'); c.set_main_option('script_location','migrations'); print(ScriptDirectory.from_config(c).get_heads())"
```

Confirm production has actually applied `374bcfa9f423` before deploying a
child of it. Note that several existing migrations guard themselves with an
inspector check (e.g. `9a6f2c4b8d1e` tests for the column before adding it),
which suggests the production DB has at times been ahead of the migration
history — worth a `SELECT version_num FROM alembic_version` against prod
rather than an assumption.

## 2. Record payments from the webhook handler

All insertion points are in `backend/app/routes/billing.py`, inside the
existing event dispatch. Write a single helper and call it from each branch:

```python
def _record_payment(*, external_reference, source, user, amount_paid, amount_due,
                    currency='usd', plan_key=None, billing_interval=None,
                    subscription_id=None, promotion_code=None, paid_at=None):
    """Idempotent by external_reference — a webhook retry is a no-op."""
```

Call sites:

| Event | Line | `source` | Amount fields |
|---|---|---|---|
| `invoice.payment_succeeded` | `billing.py:2257` | `subscription_invoice` | `inv['amount_paid']`, `inv['amount_due']` |
| `invoice.paid` (300K) | `billing.py:2255` | `limited_time_300k` | same |
| `payment_intent.succeeded` | `billing.py:2246` | `credit_pack` / `limited_time_300k` | `intent['amount_received']` |

Notes for the implementation:

- `amount_paid` is **`0` on a fully-discounted invoice**. Record the row anyway
  with `is_comped=True` — that row is the evidence a coupon was redeemed.
- Derive `discount_cents` as `amount_due - amount_paid`, and read the applied
  code from `invoice.discount.promotion_code` / `invoice.total_discount_amounts`
  when present.
- `billing_interval` is **not stored on `User` today** — the existing status
  endpoint re-derives it from the Stripe subscription
  (`billing.py:300–305`). Take it from the invoice line item's
  `price.recurring.interval` at record time rather than adding another Stripe
  round-trip later.
- The 300K fulfilment path already resolves the user and reference
  (`_fulfill_limited_time_300k_invoice`, `billing.py:671`); record inside it so
  the payment row and the credit grant commit in the same transaction.

## 3. Backfill from Stripe (decided — run once before the dashboard change)

`backend/scripts/backfill_payments.py` — page `stripe.Invoice.list` and
`stripe.PaymentIntent.list` with `created[gte]` at the first production sale,
writing rows through the same helper from step 2. Idempotent by
`external_reference`, so it is safe to re-run and safe to run while webhooks
are live.

Requirements:

- **Read-only against Stripe.** The script creates local rows; it must never
  modify a Stripe object, grant credits, or send mail. Do not reuse the
  fulfilment helpers in `billing.py` — they do all three.
- **Support `--dry-run`** printing the row count and total by source, so the
  numbers can be sanity-checked against the Stripe dashboard before writing.
- **Backfill the comped rows too.** The historical $0 redemptions are the
  evidence that the old numbers were wrong; dropping them would quietly
  reproduce the bug in reverse.
- **Run it only if at least one paying subscription is already active.** The
  point is not to recover historical revenue — if the only prior activity was
  $0 coupon testing, backfilling writes comped rows and gross revenue stays
  $0, which is the correct number.

  The actual gap it closes is MRR. MRR is derived from payment rows, so a
  subscription that is active *now* but whose last invoice predates webhook
  recording contributes nothing until it next renews — up to a month for a
  monthly plan, up to a year for an annual one. The backfill seeds those rows
  so the run-rate is right on day one. With no active paid subscriptions,
  skip it; $0 is then the honest number, not a reporting gap.

## 4. Rewrite the two metrics

Replace `admin.py:671–687` entirely. Do not keep `plan_mrr`.

```python
window_start = now - timedelta(days=30)
in_window = Payment.paid_at >= window_start

completed_purchases_30d = Payment.query.filter(
    in_window, Payment.amount_paid_cents > 0
).count()                                             # money actually received
coupon_redemptions_30d = Payment.query.filter(
    in_window, Payment.is_comped.is_(True)
).count()
gross_revenue_30d = db.session.query(
    func.coalesce(func.sum(Payment.amount_paid_cents), 0)
).filter(in_window, Payment.amount_paid_cents > 0).scalar() / 100
```

**MRR is a separate calculation and must not be summed from payments.** It is
the recurring run-rate of *currently active* subscriptions, so a $999 one-time
300K sale and a credit pack are revenue but not MRR. Compute it from the most
recent paying invoice per active subscription, normalizing annual to monthly:

```python
# monthly => amount_paid_cents; annual => amount_paid_cents / 12
```

Filter to `user.subscription_status in {'active', 'trialing'}` so a canceled
subscription drops out. Prices come from the payment rows, so per-seat team
and business accounts are finally correct without modelling seat maths, and
the catalog stops being duplicated.

## 5. Expose the distinction

In the `metrics` payload (`admin.py:695–710`), **remove `completed_purchases`**
and add:

- `completed_purchases_30d` — count of payments where `amount_paid_cents > 0`
- `coupon_redemptions_30d` — count where `is_comped` is true
- `gross_revenue_30d` — dollars collected, all sources, trailing 30 days
- `mrr` — recurring run-rate only, point-in-time

Rewrite the `notes` block (`admin.py:722–726`) to state the source of each.
The current `mrr` note — "Self-serve MRR estimate; team and enterprise
contract revenue are not inferred" — describes behaviour that will no longer
be true. Replace with something like:

```python
"mrr": "Recurring run-rate from settled Stripe invoices for active subscriptions, annual normalized to monthly. Excludes one-time purchases and any contract invoiced outside Stripe.",
"coupon_redemptions_30d": "Fully-discounted invoices. These are redemptions, not revenue, and are excluded from gross revenue and MRR.",
```

## 6. Frontend labels

`frontend/src/jaspenInterface/Admin/MasterAnalytics.jsx:10–25` — replace the
`completed_purchases` entry and add the new keys to `METRIC_LABELS`:

```js
['completed_purchases_30d', 'Completed Purchases (30d)'],
['coupon_redemptions_30d', 'Coupon Redemptions, $0 (30d)'],
['gross_revenue_30d', 'Gross Revenue (30d)'],
```

`formatMetric` (line 32) already special-cases `mrr` for currency — extend the
same branch to `gross_revenue_30d` so it renders as dollars, not a bare count.
Leaving the old key in place would render "Pending" once the backend stops
sending it, which reads as instrumentation-not-yet-built rather than renamed.

## 7. Tests

`backend/tests/test_admin_analytics_revenue.py`, all with a seeded `Payment`
table (no Stripe calls):

- a fully-discounted invoice records a payment with `is_comped=True`,
  `amount_paid_cents == 0`, raises `coupon_redemptions_30d`, and does **not**
  raise `completed_purchases_30d` or `gross_revenue_30d`
- a payment older than the window is excluded from all three 30-day metrics
  but still counts toward `mrr` if its subscription is active
- the same webhook delivered twice records **one** row (idempotency)
- a canceled subscription contributes **$0** to MRR
- an annual subscriber contributes **1/12** of the amount paid to MRR
- a $999 300K purchase raises `completed_purchases_30d` and
  `gross_revenue_30d` but **not** `mrr`
- a comped account on the essential plan with no payment row contributes
  nothing to either metric — the original bug, asserted directly

Per house practice: after writing these, break each fix deliberately and
confirm the matching test fails. The current metrics pass no test at all —
`test_admin.py:41` only asserts that the endpoint is master-admin-only, which
is why this shipped.

---

## Decisions — all settled, no blockers

1. **Backfill from Stripe.** Decided by the owner. See step 3.

2. **MRR includes Team and Business.** Deriving from payment rows removes the
   reason to exclude them: the invoice already reflects seat count, proration,
   and discount, so the per-seat pricing model needs no modelling on our side.
   Keeping them at $0 would preserve a known undercount to avoid a one-time
   jump, which is the wrong trade on a number used to make decisions.

   Consequence to expect: **MRR will rise the moment this ships**, and that
   rise is a correction, not growth. Note it wherever the number is reported.
   Enterprise contracts invoiced outside Stripe still will not appear — say so
   in the `notes` block rather than letting the omission be silent.

3. **Windows go in the key names, not the notes.** The existing dashboard's
   real failure is hidden mixed windows (see "Out of scope" below), so the new
   metrics carry their window explicitly:

   | Key | Window |
   |---|---|
   | `completed_purchases_30d` | trailing 30 days |
   | `coupon_redemptions_30d` | trailing 30 days |
   | `gross_revenue_30d` | trailing 30 days |
   | `mrr` | point-in-time run-rate, no window |

   This renames the existing `completed_purchases` key. That is deliberate and
   cheap — `MasterAnalytics.jsx` is the only consumer, and a silent change of
   meaning under an unchanged key is worse than a rename. Update
   `METRIC_LABELS` (step 6) to match, with the window visible in the label
   text: "Completed Purchases (30d)".

## Out of scope, but found during this trace

These are separate defects in the same endpoint. None is a revenue error;
listing them so they are not rediscovered one at a time.

- **`linkedin_visitors`, `youtube_visitors`, and `traffic_sources` are not
  scoped to today.** They read `all_lead_events` (`admin.py:637`), the most
  recent 500 attribution events **all-time**, and sit in a today-scoped grid.
- **`conversion_percent` divides unlike things** (`admin.py:690`): anonymous
  marketing lead events over authenticated visitor sessions.
- **`average_time_to_first_scorecard` measures session lifespan**, not time to
  first scorecard — it is `updated_at - created_at` of the session row
  (`admin.py:663–665`).
- **`activation_percent` mixes windows** (`admin.py:689`): scorecard sessions
  from any user over signups in the last 7 days.
- **`emails_captured` is an all-time `Lead.query.count()`** (`admin.py:700`).
- **`upgrades_started` is hardcoded `0`** (`admin.py:702`).
- **`todays_visitors` counts authenticated sessions only** and silently falls
  back to today's signup count when that is zero (`admin.py:646–649`), so the
  label overstates what is measured.
