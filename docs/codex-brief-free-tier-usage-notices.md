# Codex Brief: Free Tier Usage Notices

**Goal:** Before marketing launch to ~500 invited free users, add two missing user-facing gates:
1. A proactive daily AI request counter/warning for free users
2. A first-run welcome notice that explains free tier limits

The existing credit exhaustion and rate-limit error messages are already in good shape. This brief only covers the gaps.

---

## Context

Free-tier users are capped at:
- 5 AI analysis requests per hour
- 10 AI analysis requests per day
- $0.50/month thinking power budget (~1,000,000 credits)

Currently, users discover the daily cap only when they hit a 429 error. There is no proactive warning before that wall. For new users (especially invite-only beta), hitting a silent wall is a bad first impression.

**Important framing note:** Free users can hit *either* of two walls — whichever comes first:
1. The request count limit (10/day — hard count, does not flex with request weight)
2. The thinking power budget ($0.50/month — flexes with token usage per request)

The UI should not surface these as two separate systems. Use unified "approaching your limit" language that covers both. The app already uses "Thinking Power" as the primary vocabulary — lean on that.

---

## Change 1: Daily Limit Proximity Warning in the Chat Header

### What to build
Add a small usage indicator visible in the workspace when the user is on the free plan. It should signal when the user is approaching their daily request limit. Trigger a soft warning at 3 remaining; show blocked state at 0. Do not show a live counter during normal usage — only surface it as a heads-up, not a countdown.

### Backend

**File:** `backend/app/routes/ai_agent.py`

After each successful AI request, the per-plan daily limiter already tracks usage via `flask-limiter`. Expose a new lightweight endpoint (or add to an existing user-status endpoint) that returns current daily usage for the calling user.

Add to the existing `/api/ai/session/status` endpoint (or create `/api/ai/usage/daily`) — return:

```json
{
  "plan_key": "free",
  "daily_limit": 10,
  "daily_used": 4,
  "daily_remaining": 6,
  "hourly_limit": 5,
  "hourly_used": 1,
  "hourly_remaining": 4,
  "resets_at_utc": "2026-06-09T00:00:00Z"
}
```

The daily/hourly counts should be read directly from the same limiter storage that enforces the limits (`RATELIMIT_STORAGE_URI`). Do not maintain a separate counter — read from the same source flask-limiter writes to, to avoid drift.

**File:** `backend/app/billing_config.py`

The plan daily/hourly limits are already defined in `_plan_daily_limit` / `_plan_hourly_limit` in `ai_agent.py` (lines 64–96). Reference those constants; do not duplicate them.

### Frontend

**File:** `frontend/src/jaspenInterface/Workspace/JaspenChat.jsx`

- Poll (or fetch once on mount + after each request) the daily usage endpoint
- Only render the indicator when `plan_key === "free"`
- Place it in the chat input area near the send button — subtle, not alarming
- States:
  - **Normal (>3 remaining):** No indicator (don't add noise)
  - **Warning (1–3 remaining):** Small amber indicator: `"You're approaching your daily limit"`
  - **Exhausted (0 remaining):** Disable the send button; show inline message: `"You've reached your daily limit. Resets at midnight UTC."` with a link to `/account?tab=billing`

Do not say "3 requests left" or any specific count. "Approaching your limit" covers both the request-count wall and the thinking-power wall without requiring users to understand the distinction.

The existing `thinking_power_low_warning` toast pattern in `JaspenChat.jsx` (lines 4604–4610) is a good model to follow for tone and placement.

---

## Change 2: First-Run Free Tier Welcome Notice

### What to build
A one-time dismissible notice shown to free users on their first workspace session. Explains what they get and sets expectations. Should not require any new backend work — use the existing `ui_preferences` field already synced via `AuthContext`.

### Backend

**File:** `backend/app/models.py` or `backend/app/billing_config.py`

Add a `ui_preferences` key: `"free_tier_welcome_dismissed": false`

Set it to `true` when the user dismisses the notice. Use the existing `ui_preferences` update endpoint — do not create a new one.

### Frontend

**File:** `frontend/src/jaspenInterface/Workspace/JaspenChat.jsx` (or the workspace shell)

Show a dismissible banner/modal on first load when:
- `plan_key === "free"` AND
- `ui_preferences.free_tier_welcome_dismissed !== true`

**Copy (exact):**

> **Welcome to Jaspen — here's what you get on the free plan**
>
> - 10 AI-powered analyses per day (5 per hour)
> - 1,000,000 thinking credits per month
> - Full access to all features — scorecards, scenarios, execution plans, and connectors
> - Resets monthly on your signup anniversary
>
> Need more thinking power? [View plans →](/account?tab=billing)
>
> [Got it]

On dismiss: PATCH `ui_preferences.free_tier_welcome_dismissed = true`. Do not show again.

Style: use the existing info-banner component pattern in the workspace. Keep it one-line collapsible if a compact variant exists.

---

## What NOT to change

- The existing 429 rate-limit error message — it is clear and includes retry time
- The `thinking_power_exhausted` (402) error message — it already includes reset datetime and upgrade URL
- The 5% grace overage on credits — this is intentional and acceptable
- The global 200 req/min limiter — this is a DDoS guard, not a plan gate; leave it alone
- Any paid-tier behavior — these changes are free-plan-only

---

## Acceptance criteria

1. A free user who has used 7/10 daily requests sees an amber "You're approaching your daily limit" indicator near the send button — no specific count shown.
2. A free user who has used 10/10 requests sees the send button disabled with "You've reached your daily limit. Resets at midnight UTC."
3. A brand-new free user sees the welcome notice on first workspace load and never sees it again after dismissing.
4. Essential/Team/Enterprise users see none of these UI changes.
5. The daily usage endpoint reads from the same limiter storage that enforces limits — no counter drift possible.
