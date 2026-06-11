# Codex brief — credit-pack purchase grants credits but sidebar doesn't update

## Symptom
Buying a credit pack succeeds in Stripe and the invoice/receipt shows in the
in-app Invoices tab, but the "Thinking power" credits in the sidebar do not
increase. Reproduced on the **Team** plan (account "HILLSBORO ROW…").

## Root cause (confirmed by read-only trace)
The grant path itself is correct; the bug is a **persistence gap in the
shared-pool branch of `add_credits`**.

1. Credit pack → `_create_credit_pack_checkout_session` (billing.py:787) sets
   metadata `checkout_type='credit_pack'`, `tokens`, `user_id`. Hosted Checkout.
2. Webhook `checkout.session.completed` (billing.py:944–972) reads `tokens` and
   calls `add_credits(user, tokens)`. **This part works.**
3. `add_credits` (billing_config.py:528) branches on plan:
   - **Individual plans** → user-pool branch (lines 546–556): mutates the meter
     in `user.ui_preferences['thinking_power']`, then PERSISTS it
     (`user.ui_preferences = deepcopy(prefs)` + `_flag_modified(user, ...)`).
     ✅ Works.
   - **Shared-pool plans** (`team`, `enterprise` — `SHARED_POOL_PLANS`,
     billing_config.py:109) → org-pool branch (lines 534–544): mutates
     `pool["meter"]` and sets `user.credits_remaining`, then `return`s —
     **but never writes back to `org.settings` and never calls
     `_flag_modified(org, "settings")`.** ❌ Lost.

Why "never writes back" matters: `_resolve_org_pool` (billing_config.py:413)
persists the meter as a **deepcopy** —
```
447  settings["thinking_power"] = meter
448  org.settings = deepcopy(settings)     # <-- persisted object is a COPY
449  _flag_modified(org, "settings")
...
454  "meter": meter,                       # <-- returns the ORIGINAL, detached
```
So `pool["meter"]` returned to `add_credits` is **not** the object stored on
`org.settings`. Mutating it changes a throwaway dict. On the next `/billing`
read, `_resolve_org_pool` rebuilds `remaining` from `org.settings` (where
`overage_tokens` is still 0) → display snaps back to the monthly limit (29,000).

For Team users the sidebar "remaining" comes from the **org** meter, not
`user.credits_remaining`, which is why setting `user.credits_remaining` alone
(as the org branch does) has no visible effect.

## The one small proven change
In `add_credits`, make the org-pool branch persist exactly like
`_resolve_org_pool` does — read the meter from `org.settings`, bump it, write it
back with a deepcopy + `_flag_modified`. Replace lines ~534–544:

```python
    if plan_key in SHARED_POOL_PLANS:
        pool = _resolve_org_pool(user, {}, now=datetime.utcnow(), force_reset=False)
        if pool is not None:
            org = pool["organization"]
            settings = org.settings if isinstance(org.settings, dict) else {}
            meter = settings.get("thinking_power") if isinstance(settings.get("thinking_power"), dict) else {}
            meter["overage_tokens"] = _coerce_non_negative_int(meter.get("overage_tokens")) + amount
            meter["cycle_limit"] = _coerce_non_negative_int(meter.get("cycle_limit")) + amount
            meter["remaining"] = int(meter.get("remaining", 0)) + amount
            meter["tokens_used_this_month"] = max(0, int(meter.get("cycle_limit", 0)) - int(meter.get("remaining", 0)))
            settings["thinking_power"] = meter
            org.settings = deepcopy(settings)          # persist the COPY that org actually keeps
            _flag_modified(org, "settings")            # tell SQLAlchemy the JSON changed
            user.credits_remaining = int(meter.get("remaining", 0))
            user.credits_reset_at = datetime.utcnow()
            return
```
Key difference vs. current code: read `meter` from `org.settings` (not the
detached `pool["meter"]`), and **re-persist** with `org.settings = deepcopy(...)`
+ `_flag_modified(org, "settings")`. Mirrors the user-pool branch and
`_resolve_org_pool` itself.

Nothing else changes. Do not touch the webhook or invoices code — they're correct.

## Why this is low-risk
- Scope: one branch of one function. Individual-plan path untouched.
- It only adds the persistence that the parallel user-pool branch already does.
- `_resolve_org_pool` already preserves `overage_tokens` on read (line 422), so
  once it's actually persisted, refreshes will keep the purchased credits and the
  monthly reset (line 432–438) still correctly zeroes overage at cycle end.

## Verify (test mode)
1. Note the org's current `remaining` (sidebar + `/billing` response).
2. Buy a credit pack (e.g. 3,000) as a Team user; let the webhook fire.
3. Backend log should show "added 3000 credit-pack tokens for user=…".
4. Refresh /account → sidebar "Thinking power remaining" should be old + 3000,
   and persist across reloads (proves it's in `org.settings`, not transient).
5. Confirm an **individual-plan** account still grants correctly (no regression).
6. Optional DB check: `org.settings['thinking_power']['overage_tokens']` > 0 and
   `['remaining']` bumped.

## One thing to double-check while you're there
If `_active_org_for_user(user)` returns `None` for a Team user (no active org
row), `_resolve_org_pool` returns None and `add_credits` falls through to the
user-pool branch (which persists fine) — but the *display* for a `team` plan may
still read the org pool and show no change. If the verify step shows the grant
landing in `user.ui_preferences` instead of `org.settings`, the real gap is a
missing/!active org for this account, not the persistence bug above. Check which
branch actually runs (a one-line log at the top of each branch settles it).
