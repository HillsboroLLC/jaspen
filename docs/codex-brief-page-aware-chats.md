# Codex brief — make the page-level Jaspen chats context-aware of their page

## Goal
The standalone "Ask Jaspen" helper chat appears on several non-workspace pages
(Account/Billing, Knowledge, Data Sources/Connectors, Team). Today it can't tell
which page it's on for three of them, so answers are generic. Make each chat aware
of (a) which page it's on and (b) which sub-section/tab is active, so it can give
grounded help.

## Architecture (already in place — do NOT rebuild)
- There is **one shared chat**, not four. `PersistentAiSidebar.jsx`
  (frontend/src/jaspenInterface/shared/) renders the panel and calls
  `useJaspenAI().sendMessage` (line ~57/86). It's mounted globally via
  `JaspenAIProvider` (App.js), so it rides along on every route.
- The provider already attaches page context to every message. In
  `shared/JaspenAIContext.jsx`:
  - `getViewContext()` (lines 34–41) returns `{ current_view }` from the path.
  - It's read at send time (line 90) and sent as `view_context` (lines 102/112/122).
- **The backend already consumes it.** `view_context` is whitelisted to these keys
  only: `current_view, active_tab, active_scorecard_id, active_scenario_id,
  wbs_summary` (ai_agent.py:9239/9244 and 9820/9825; strategy.py:8409–8414 — any
  other key is dropped). `current_view` drives:
  - model routing — `_PROCESSING_VIEWS` / `_JUDGMENT_VIEWS` (ai_agent.py:787–796), and
  - the system prompt — "- Current view: {current_view}" (ai_agent.py:1109–1111),
    plus per-view guidance blocks (ai_agent.py:1177 summary / 1188 scenario /
    1195 execution).

### The actual gap
`getViewContext()` only maps `/new`, `/execution-plan`, `/connectors-manage`,
`/insights`. **`/account`, `/knowledge`, `/team` fall through to `current_view:
'general'`**, so the model is never told it's on those pages, and there's no
prompt guidance for them. (Connectors is mapped to `connectors` but also has no
guidance block.)

## Tier 1 — ship now (small, low-risk, centralized)

### 1. Frontend: map the missing pages (+ pass the active tab)
In `shared/JaspenAIContext.jsx`, extend `getViewContext()`:
```js
const getViewContext = useCallback(() => {
  const p = location.pathname;
  const params = new URLSearchParams(location.search);
  const activeTab = params.get('tab') || undefined;   // Account uses ?tab=invoices etc.
  if (p === '/new') return { current_view: 'workspace' };
  if (p === '/execution-plan') return { current_view: 'execution' };
  if (p === '/connectors-manage') return { current_view: 'connectors' };
  if (p === '/insights') return { current_view: 'insights' };
  if (p === '/account') return { current_view: 'account', active_tab: activeTab };
  if (p === '/knowledge') return { current_view: 'knowledge' };
  if (p === '/team') return { current_view: 'team' };
  return { current_view: 'general' };
}, [location.pathname, location.search]);
```
Notes:
- `active_tab` is already a whitelisted key, so no backend schema change needed.
  Account's buckets are overview / plans / packs (credit packs) / invoices /
  security (Account.jsx `activeTab`, line 359) and they live in `?tab=`.
- Add `location.search` to the dependency array (shown above).

### 2. Backend: add per-view guidance blocks
In ai_agent.py, where the per-view prompt guidance is assembled (near 1177–1195,
the `if current_view == "summary": ... elif ...` chain), add cases for the new
views. Keep them short and scoped — what the page is for, what the assistant can
help with, and what it must NOT claim to do (it can't perform billing actions or
change settings; direct the user to the page controls). Example shape:
```python
elif current_view == "account":
    lines.append(
        "The user is on the Account / Billing page. Help them understand their "
        "plan, thinking-power (credit) usage and reset date, credit packs, and "
        "invoices. You can explain and interpret; you cannot change the plan, buy "
        "credits, or alter settings — point them to the on-page controls for that."
    )
    if active_tab:
        lines.append(f"They are viewing the '{active_tab}' section of Account.")
elif current_view == "knowledge":
    lines.append(
        "The user is on the Knowledge/Docs page. Answer 'how do I…' product "
        "questions about Jaspen's workflow (discovery → scoring → scenarios → WBS "
        "→ connectors). Prefer concise, step-oriented answers."
    )
elif current_view == "team":
    lines.append(
        "The user is on the Team page. Help with members, roles, seat policy, and "
        "shared-project visibility. You can explain seat math and roles; actual "
        "invites/role changes happen via the on-page controls."
    )
elif current_view == "connectors":
    lines.append(
        "The user is on the Data Sources / Connectors page. Help with connector "
        "setup, sync modes, conflict policy, and health checks for Jira, "
        "Smartsheet, Salesforce, Snowflake, etc."
    )
```
(`active_tab` is already normalized into the context dict alongside
`current_view` — see ai_agent.py:1025–1027; reuse that variable.)

### 3. Backend: model routing for these views
Check `_PROCESSING_VIEWS` / `_JUDGMENT_VIEWS` (ai_agent.py:787–796). These four
pages are lightweight Q&A, not data processing — route them to the same cheap/
fast path the other help-style views use (do NOT send them down the heavy
scoring/processing model). Add `account`, `knowledge`, `team`, `connectors` to
whichever set represents the light Q&A path. Confirm by reading the set
definitions; pick the one that keeps cost/latency low. (Per project routing
strategy: judgment→Claude, processing→Gemini; these are simple interpretive Q&A,
so match them to the existing help/companion routing rather than scoring.)

That's the whole Tier-1 change: one JS function + one prompt chain + one routing
set. It degrades gracefully (unknown tab → just omitted) and touches nothing in
the scoring/workspace path.

## Tier 2 — OPTIONAL, defer unless Tier 1 feels thin
Give the chat the page's *live data* (e.g. "you're on Team, 100% remaining, resets
Jul 1; 4 connectors, Jira may be outdated") instead of only the page name.
- Add a tiny `pageFacts` setter to the provider (`setPageFacts(obj)`), and have
  each page set a SMALL, NON-SENSITIVE snapshot on mount/update:
  - Account: plan name, % thinking power remaining, reset date, invoice count.
  - Team: seat usage (admin x/y, paid seats, viewers).
  - Connectors: list of connected + which are "may be outdated".
- Whitelist ONE new key (e.g. `page_facts`, a short stringified summary — not raw
  objects) in the backend `view_context` filters (the lists at ai_agent.py:9244 /
  9825 and strategy.py:8414) and append it to the prompt near the
  "- Current view:" line.
- Privacy: only include figures already shown on the page; no emails, tokens,
  customer ids, or other PII. Keep it a few short fields.

Why defer: it adds per-page wiring + a schema change + a privacy surface. Tier 1
already makes the chats genuinely page-aware; Tier 2 is a polish pass.

## Recommendation
Ship **Tier 1** — it's cheap and removes the "generic answers" problem. **Keep the
chats** (don't remove them); the only reason they feel weak today is the 3 missing
view mappings. Defer Tier 2 until after launch.

## Verify
1. Visit `/account?tab=invoices`, open the chat, ask "how close am I to my thinking
   power limit?" → answer should reference the Account/billing context (plan,
   remaining, reset), not a generic reply.
2. Network tab: the POST body's `view_context` should show
   `current_view: "account", active_tab: "invoices"`.
3. Repeat on `/knowledge` (`current_view: "knowledge"`), `/team` (`"team"`),
   `/connectors-manage` (`"connectors"`).
4. Confirm `/new` workspace + `/execution-plan` behavior is unchanged (no
   regression in the scoring/companion path).
5. Confirm these Q&A views route to the light model (check latency/logs), not the
   heavy scoring model.
