# Codex Brief: Continuous Conversation + Anchored Artifacts + Workspace Editing

## Audience and tone

You are Codex. This brief is prescriptive. **Do not improvise. Do not introduce new logic, new endpoints, new state, new fields, new components, or new architecture beyond what is described here.** If anything below is ambiguous, has multiple valid interpretations, or conflicts with existing code you find, **stop and ask Bailey (the user) for alignment before writing code.** Phrases that should prompt a question: "I assume...", "It looks like...", "I could also...". Don't assume; ask.

The trash-button bug is already fixed. **Skip everything related to delete confirms.**

## The product model (the rules of the game)

Jaspen is a chat-first product. There is ONE conversation surface (`/new` in the SPA, rendered by `frontend/src/jaspenInterface/Workspace/JaspenChat.jsx`). The four pills (Discovery, Scoring, Trade-off, Execution) are **navigational only**: clicking a pill changes which insights the right sidebar emphasizes. The pills never swap what's rendered in the main chat panel.

During a conversation, the user may produce three kinds of **artifacts**:

1. **Scorecard** — a structured score for an idea (jaspen_score 0–100, six dimension scores, top risks, recommendations).
2. **Trade-off comparison** — a ranked comparison of two or more scorecards.
3. **Execution plan** — a WBS of phases and tasks for a chosen scorecard.

Each artifact, once created, lives **inline in the chat thread at the position where it was created**. Like message bubbles. The user can scroll up and see, in order: chat → chat → scorecard → chat → chat → tradeoff → chat → scorecard → chat → execution-plan → chat. Same way ChatGPT artifacts and Claude artifacts work.

Each artifact has an **"Open in Workspace ↗"** button that opens a dedicated edit canvas in a new tab. The canvas autosaves (debounced PATCH). Workspace is the same component (`frontend/src/jaspenInterface/Workspace/JaspenWorkspace.jsx`) routed by `/workspace/:threadId/:scorecardId`.

The user can also access artifacts via a "Session Artifacts" dropdown at the top of the chat. Clicking an artifact in the dropdown scrolls to the inline artifact in the chat OR opens it in Workspace via Edit ↗.

---

## What's broken

### Problem 1: Scorecards (and other artifacts) get generated when the user is just having a conversation

The agent currently emits a trigger phrase ("Building your scorecard now.") at the end of its reply, and the frontend regex-matches that phrase to auto-fire scoring. The regex is too loose. The agent also fires scoring on `data.status === 'ready_to_analyze'` from the backend. Result: phantom scorecards appear when the user asks clarifying questions, confirms a previous result, or has any back-and-forth.

The previous fix (commit `172bd53`) removed the frontend auto-fire branches. That partially worked but now there's no clean way for the agent to actually generate a scorecard either — it has to rely on phrase matching, which is the fragile thing we want to replace.

### Problem 2: Artifacts don't stay anchored where they were created

- **Scorecards** are stored in `session.scorecard_snapshots` (backend) and woven into the chat thread on the frontend by matching trigger-phrase positions in `messages` to snapshot indices (`displayMessages` useMemo in `JaspenChat.jsx`). When the trigger-phrase positions shift (extra phrases, edited messages), the anchor breaks and scorecards reorder.
- **Trade-off** and **Execution Plan** artifacts are NOT persisted as messages in the chat history. They're derived from `scorecardSnapshots` and `threadWbs` state, then appended at the END of `displayMessages` regardless of where they were actually created. This is wrong — they should live at the point in the conversation where they were generated.

### Problem 3: "Edit in Workspace" doesn't always open the artifact fully

- **Execution plan** workspace works (per Bailey).
- **Trade-off workspace** at `/workspace/<tid>/__tradeoff__` shows the empty state `"Score an idea in the conversation — it will appear here automatically"` even when scorecards exist. **Confirmed root cause:** CORS preflight failure. The frontend sends `Cache-Control: no-store` in `fetchBundle` (`frontend/src/jaspenInterface/Workspace/JaspenClient.jsx`), and the backend's CORS config does not include `Cache-Control` in `Access-Control-Allow-Headers`. Browser blocks the preflight, fetch never happens. See the console screenshot Bailey shared — the error is unambiguous.
- **Scorecard workspace** — verify it works after the CORS fix. Same code path.

### Problem 4: Hide / reveal scorecards in the trade-off

This is partially built. `tradeoff_included` boolean lives in `display_overrides` per scorecard. The Trade-off table has eye icons that toggle it. The chat-side scorecard card shows a small "Parked from trade-off · Include" pill when excluded. **Verify this still works end-to-end after the other changes. Do not redesign it.**

---

## What Codex needs to do (in this exact order, four focused commits)

### Commit 1: Replace trigger-phrase scoring with explicit tool calls

**The intent:** Move artifact generation from "AI emits a magic phrase that frontend regex-matches" to "AI decides to call a tool by name." This is how every other agent product (Manus, OpenAI assistants, Claude with tools) works.

**Read first:**
- `backend/app/routes/ai_agent.py` — the chat-agent system prompt (~line 450) and the tool registry section (search for `_anthropic_tool_specs` or wherever Anthropic tools are registered).
- `backend/app/tool_registry.py` — existing tool definitions for `create_scenario`, `update_wbs_task`, `add_wbs_task`, `remove_wbs_task`, `generate_execution_plan`, `rename_thread`, etc. Follow the same pattern.
- `frontend/src/jaspenInterface/Workspace/JaspenChat.jsx` — search for `triggerInlineScore`, `triggerAutoVersion`, and the regex `/building your scorecard|scorecard now|generating your scorecard|scoring your idea/` (it appears in three places). These are the auto-fire paths.

**Do:**

1. Add three new Anthropic tools to the registry:
   - `generate_scorecard` — input: `{ idea_description, name }` — output: a freshly-scored scorecard payload (the existing `_generate_jaspen_scorecard` flow, just invoked via tool-call instead of phrase-match).
   - `generate_tradeoff_comparison` — input: `{ scorecard_ids: [] }` (optional; defaults to all included scorecards) — output: a tradeoff summary artifact id that the frontend can render.
   - `generate_execution_plan` — input: `{ scorecard_id }` — output: an execution plan WBS for the chosen scorecard (existing `handleGenerateAiWbsFromScorecard` backend flow).

2. Update the system prompt:
   - Remove every mention of the literal trigger phrase `"Building your scorecard now."`
   - Replace with: "When the user proposes a NEW idea, variation, or parameter change that warrants a fresh score, call the `generate_scorecard` tool. When the user asks to compare or rank ideas, call `generate_tradeoff_comparison`. When the user asks to build an execution plan, call `generate_execution_plan`. Use your judgment — confirmations, acknowledgments, and read-only questions never need a tool call."

3. Wire tool execution:
   - When the agent calls `generate_scorecard`, the backend runs the existing scoring logic and **appends a new message** to `session.chat_history` with `role='ai'` and `artifact: { type: 'scorecard', data: {...} }` (or extends the assistant message with the artifact field — pick ONE approach and confirm with Bailey).
   - Same pattern for the other two tools.
   - The streamed response payload includes the new message(s) so the frontend can append them to its `messages` state.

4. Delete the trigger-phrase regex on the frontend (all three call sites in `JaspenChat.jsx`). Tool-call detection comes from the backend response shape, not text matching.

5. Delete the `_detect_rescore_action` function on the backend (search `_RESCORE_SUGGESTION_RE`) — no longer needed.

**Don't:**
- Don't change the existing scoring math, scoring prompt, or `_generate_jaspen_scorecard` function. Only the invocation path changes.
- Don't add any new fields to the scorecard JSON.
- Don't touch the User Settings drawer, Insights panel, lightning bolt, pills, or any non-conversation UI.
- Don't change the existing tools (`create_scenario`, `update_wbs_task`, etc.).

**Questions to ask Bailey before starting:**
- Does the agent system prompt for "when to score" need any additional examples beyond what's in the existing prompt? (Bailey already pared this down — confirm before adding new ones.)
- Should `generate_scorecard` and the existing `create_scenario` tool coexist, or does `create_scenario` become a wrapper around `generate_scorecard`? (Existing `create_scenario` is what powers "+ New Version" — be careful not to break it.)
- When the agent is unsure, should it ask the user before scoring, or silently skip? (Current prompt says "ask"; confirm.)

---

### Commit 2: Anchor every artifact to the message that created it

**The intent:** Artifacts stay where they were created in the chat thread, forever. Not at the bottom. Not anchored to a fragile trigger-phrase position.

**Read first:**
- `frontend/src/jaspenInterface/Workspace/JaspenChat.jsx` — the `displayMessages` useMemo (around line 5860). Note the `triggerRegex` weaving logic.
- `frontend/src/jaspenInterface/Workspace/JaspenChat.jsx` — `_withDerivedArtifacts` helper. This is the one appending tradeoff/execution at the end. Wrong.
- `backend/app/routes/ai_agent.py` — `session.chat_history` structure. Each entry has `role`, `content`, `timestamp`. Some have `mutations`, some have `undo`.

**Do:**

1. **Chat history is the source of truth.** Once Commit 1 lands, every artifact (scorecard, tradeoff, execution plan) is appended to `session.chat_history` as its own message at creation time:
   ```python
   {
     "role": "ai",
     "content": "",
     "artifact": {"type": "scorecard", "data": {...}},
     "timestamp": "...",
     "anchor_message_index": <index of the assistant message that called the tool>
   }
   ```
   The `anchor_message_index` is informational; the position in `chat_history` is what matters for rendering.

2. **Rip out the `displayMessages` weaving.** No more trigger-phrase matching. No more `_withDerivedArtifacts`. The `messages` state on the frontend already reflects `chat_history` from the backend. Render messages in array order. Each message renders via `renderConversationMessage`, which already handles `artifact` types.

3. Verify the existing `renderConversationMessage` handles all three artifact types (it already handles `scorecard`, `scorecard-loading`, `tradeoff`, `execution_plan` — confirm none of those changed shape).

4. On thread restore (page reload), the backend returns the full `chat_history` including artifact messages, so the conversation reconstructs naturally with artifacts in the right places.

5. Remove `threadWbs` and `scorecardSnapshots` from any path that re-derives display state — they remain as state for the workspace canvas and for the Insights panel, but the chat thread reads only from `messages`.

**Don't:**
- Don't change the visual rendering of the artifact cards. They look fine. Only the positioning logic changes.
- Don't migrate old threads (existing scorecards that aren't anchored to a message). Bailey's existing test thread can be deleted. New threads get the right behavior.
- Don't add a "regenerate artifact" feature, an "edit artifact in place" feature, or any new buttons.

**Questions to ask Bailey:**
- For threads that ALREADY exist with `scorecard_snapshots` but no anchored chat messages, do you want a one-time migration that synthesizes artifact messages at the end of the chat, or just let those threads stay as-is and have new threads use the new model? (Recommendation: stay as-is. New behavior applies going forward.)
- Should the tradeoff and execution artifacts be re-generatable (i.e., a new tool call replaces the old artifact message), or only ever added (so multiple versions live in the chat)? (Recommendation: re-generatable — agent calls the tool again, old artifact stays in the chat history at its original position, new artifact appended at current position.)

---

### Commit 3: Fix Edit in Workspace for trade-off + verify all three artifact types

**The intent:** Every "Edit in Workspace ↗" button — wherever it appears (on the artifact card itself, or in the Session Artifacts dropdown) — opens the artifact fully in the workspace canvas with autosave.

**Read first:**
- `frontend/src/jaspenInterface/Workspace/JaspenClient.jsx` — `fetchBundle` function (line ~840). The bug is here.
- `backend/app/__init__.py` — CORS configuration (search for `CORS(` or `Access-Control-Allow-Headers`).
- `frontend/src/jaspenInterface/Workspace/JaspenWorkspace.jsx` — the workspace component. Handles `__tradeoff__`, `__execution__`, and regular scorecard IDs.

**Do:**

1. **Remove the `Cache-Control: no-store` header from `fetchBundle`.** It was added to keep the bundle fresh during dev, but it triggers a CORS preflight that the backend rejects. Either:
   - **Option A (preferred):** Delete the `Cache-Control` header line from `fetchBundle`. Browser cache headers on the backend response will handle freshness. One-line change.
   - **Option B:** Add `Cache-Control` to the backend's CORS `allow_headers` list. Backend change. Slightly less risky if there's a reason `no-store` was added.
   
   Ask Bailey which to do. Recommendation: Option A. The cost of a slightly stale bundle is tiny; the cost of a broken workspace is high.

2. **Verify all three artifact types open in workspace** after the CORS fix:
   - `/workspace/<tid>/__tradeoff__` — renders `TradeoffView` with bundle.scorecard_snapshots.
   - `/workspace/<tid>/__execution__` — renders `JaspenExecutionCanvas` with thread WBS.
   - `/workspace/<tid>/<scorecard_id>` — renders the scorecard edit shell.
   
   Open each manually and confirm. If any one is still broken, ask Bailey before touching code — don't guess at the cause.

3. **Verify autosave** is wired for each canvas:
   - Execution canvas: existing debounced save via `Jaspen.upsertThreadWbs` (already works per Bailey).
   - Scorecard canvas: existing `Jaspen.patchScorecardOverrides`.
   - Trade-off canvas: park/un-park toggle persists via `patchScorecardOverrides`. There is no other editable field on the trade-off canvas — confirm with Bailey what "edit" means there. If she expects to edit names / status pills / etc., that's new feature work — ask before doing anything.

4. **Verify "Edit in Workspace" links exist:**
   - On the inline scorecard card in chat — existing button (do not touch).
   - On the inline tradeoff artifact — should link to `/workspace/<tid>/__tradeoff__`.
   - On the inline execution artifact — should link to `/workspace/<tid>/__execution__`.
   - In the Session Artifacts dropdown — links should exist for each artifact type.
   
   If any link is missing or points to the wrong URL, fix it. Otherwise don't touch.

**Don't:**
- Don't change the workspace canvas layouts, colors, or interactions.
- Don't add new CTAs on the artifact cards.
- Don't change the URL scheme. `/workspace/:tid/:cid` stays as-is.
- Don't add a "viewer mode" or "lock state" or anything beyond what's described.

**Questions to ask Bailey:**
- Option A or B for the CORS fix?
- Is there anything editable on the trade-off canvas beyond the park/un-park toggle? (If yes, it's out of scope here — flag it for a follow-up.)

---

### Commit 4: Verify hide/reveal scores still works end-to-end

**The intent:** Bailey already has the park/un-park feature on scorecards (`tradeoff_included` boolean in `display_overrides`). Verify it survives commits 1–3 unchanged. Do not redesign.

**Read first:**
- `backend/app/routes/strategy.py` — `_ALLOWED_OVERRIDE_KEYS` and `_coerce_override_value` (search). Make sure `tradeoff_included` is there.
- `frontend/src/jaspenInterface/Workspace/TradeoffView.jsx` — `deriveIdeas`, `PortfolioRow`, `handleToggleInclude`. The eye icon column and the optimistic local-state override.
- `frontend/src/jaspenInterface/Workspace/JaspenChat.jsx` — scorecard card "Parked from trade-off · Include" pill (search for `tradeoff_included === false`).

**Do:**

1. Open the chat with a thread that has 3+ scorecards.
2. Toggle one off via the Trade-off table's eye icon. Confirm:
   - The row greys in the trade-off table.
   - Session Avg, Ideas Scored, Top-3 Capture recompute over included only.
   - The scorecard card in the chat thread shows a "Parked from trade-off · Include" pill at the bottom.
   - Reload the page — the toggle state persists.
3. Click "Include" on the scorecard card in chat. Confirm the row springs back to its rank in the trade-off table.

**Don't:**
- Don't redesign the eye icon, the pill, or the column layout.
- Don't add a "hide from chat thread entirely" option unless Bailey explicitly asks (she hasn't — the existing park/un-park is what she meant by "hide/reveal scores").

**Questions to ask Bailey:**
- Confirm: "hide/reveal scores" = the existing tradeoff_included park/un-park, right? Or do you mean something else (e.g., hide the scorecard message from the chat thread entirely)?

---

## What NOT to touch (any commit)

- Trash / delete dialog flow — fixed.
- The Insights panel (right sidebar) — collapsible state, content, anything.
- The lightning bolt + Thinking Power percentage display.
- The User Settings drawer.
- Pills (Discovery / Scoring / Trade-off / Execution) navigation — they already correctly do nothing to the chat panel after the last batch.
- The "Stop" button.
- CORS configuration broadly — only the `Cache-Control` header issue.
- Anthropic API tier selection, model picking, credit math.
- Any backend tables, migrations, or models.

---

## How to verify each commit

After EACH commit:
1. Hard refresh `jaspen.ai/new` (Cmd+Shift+R).
2. Start a fresh thread with: "I want to launch a B2B SaaS analytics tool for HR teams."
3. Watch what happens. Note exactly which artifacts (if any) appear and where they appear in the chat.
4. Send a clarifying question: "What's my biggest risk on this idea?" — expect a text reply with NO new scorecard.
5. Send a variation: "What if we pivot to mid-market healthcare instead?" — expect a NEW scorecard inline at THIS point in the chat.
6. Scroll up — the first scorecard should still be at its original position.
7. Send "Compare these two." — expect a Trade-off artifact inline at THIS point.
8. Click "Build Execution Plan" on either scorecard — expect an Execution Plan artifact inline (or, if Bailey clarifies, at the bottom).
9. Click "Edit in Workspace ↗" on each artifact. Each should open the workspace canvas with the correct data.

If ANY of these don't behave as described, STOP and ask Bailey.

---

## Final rules

- **No new logic beyond what's described above.** If you find a tempting refactor while reading, write a note for Bailey and move on. Don't act on it.
- **Ask before making any change that's ambiguous in this brief.** Specifically: every "Questions to ask Bailey" bullet above is a real question. Get the answer before writing code in that section.
- **Commit boundaries matter.** Don't combine commits. Don't push without confirming green build (Vercel for frontend, gunicorn reload for backend).
- **Test from a real browser session before declaring done.** Console errors matter; the user has been burned by silently failing fetches.

That's it. Run questions by Bailey, then start with Commit 1.
