# Jaspen — Next Steps

> Working punch list. Current state: the core loop works end-to-end in `/new` —
> talk → agent interviews you → deterministic scoring on YOUR criteria → cards +
> ranked trade-off render live, with connectors + disclaimer present. Backup/restore
> point: branch `backup/pre-studio-20260603`, tag `pre-studio-baseline`.

## A. Insights placement + lifecycle (start here next session)
> CORRECTION from review: the "What separates them" block was added to the inline
> trade-off CARD (works — key differentiator + per-option strongest/weakest). But:
1. **Trade-off insights belong in the RIGHT SIDE PANEL** (Jaspen Insights), not just
   the card. Surface there: key differentiator, per-option wins/losses, and the
   portfolio recommendation (`score-batch` already returns `portfolio_summary`).
2. **PRINCIPLE — card ↔ workspace parity:** anything shown on an artifact's visual
   MUST also appear in that artifact's Workspace view. "What separates them" is on
   the chat card but missing from `TradeoffView` (the Workspace trade-off) — fix
   that, and treat parity as a rule for all artifacts going forward.
3. **Side-panel lifecycle — anchored, not infinite:** the insights sidebar shows
   *evolving* insights as the user interacts with the chat; they stay accessible
   from that point forward, but **freeze/anchor once the user moves on** — an old
   idea's insights must not keep mutating indefinitely. Design: snapshot the
   insight set per interaction moment; show the live one while active, keep prior
   ones as accessible (frozen) history.
- DONE: "LinkedIn Ads"/baseline label fix (1016022) — verified.
- DONE (card only): inline trade-off "What separates them" (fb9079a) + dimension
  backfill for old sessions (f345c1c). Re-home to sidebar + add to Workspace.

## B. Core capabilities the vision needs
3. **Uploads** — score ideas from Word / PowerPoint / Excel files (parse the doc
   into ideas + optionally criteria; attach is already in the composer).
4. **Connectors feed scoring** — use Jira/Salesforce/Snowflake (and uploads) to
   ground a dimension: "look in the database and answer this," then score with
   that evidence (raises confidence from assumed → evidence-backed).
5. **Exports** — download any artifact as PDF / Excel / Word.
6. **Conversational edit / re-score** — "re-score Content assuming a 6-month
   horizon," "swap the weights," "use our brand colors." (In-place re-score
   mostly exists — verify it works cleanly in this flow.)
7. **Execution plan** — generate from the winning idea; use the interface to help
   execute from an admin perspective.

## C. Architecture / cleanup (when ready)
8. **Storage swap to standalone artifacts** (kill baseline/scenario). NOTE: the
   "Scorecard" mislabel we patched is a *symptom* of the baseline model — swapping
   storage removes that whole class of bug structurally. Tables already built
   (`studio_workspaces`, `studio_artifacts`). Do it methodically.
9. **Choice-prompt primitive** — let the agent offer in-app option-boxes (confidence
   threshold to auto-generate, export format, which to score first) with the
   ability to warn/push back.
10. **Theming** — org default theme + per-artifact override (brand colors on docs).
11. **Persist studio chat history** (and load past workspaces) if we keep the studio path.
12. **Remove the separate `/studio` page** (we're focused on `/new`) — see
    `LEGACY_REMOVAL_LIST.md`.
13. **Fix the multi-head Alembic migration tangle** (6 heads) — separate cleanup.

## D. Quality / validation
14. Keep sanity-checking scores across more domains (held up well so far).
15. Confirm the progress banner + live-render behave on slower/longer batches.

> RESTORE POINTS: `backup-20260604-1955` (tag) / `backup/20260604-1955` (branch) @ f1e9ace
> — taken after B1+B2 upload/agent-batch fixes. Earlier: `pre-studio-baseline` tag.
> Dead-code removal (/studio etc.) deferred to its own backup→remove→test→restore session.

## 🔴 BUGS FOUND IN 6/4 PM TEST (triage first — diagnosed, not yet fixed)
> Root finding: there is ONE codebase / ONE deploy. The "two experiences" were the
> SAME code taking two different agent paths, not an old vs new version.
B1. ✅ FIXED (36bcd81, NEEDS DO DEPLOY) — added a HARD RULE to the agent prompt:
    multi-option requests must always queue_scorecards (batch) + set_scoring_rubric
    first when the user gave criteria; never drop to a single generic-rubric card.
B2. ✅ FIXED (36bcd81, frontend/Vercel) — data files (Excel/CSV/etc.) are now read
    BEFORE the message sends and folded into the agent's context, so the agent sees
    the file instead of replying "I don't see a file" with a disconnected analysis.
    NOTE: image/PDF/Word still go through the native attachment path (unchanged).
~~B1 (original).~~ **Agent reliability — falls into the single-card generic fallback.** When the user
    gives multiple options (+ criteria), the agent should ALWAYS `set_scoring_rubric`
    then `queue_scorecards` (batch). Sometimes it skips both and calls
    `generate_scorecard` on ONE idea, which hits the built-in default 6-dim rubric
    (Strategic Fit / Cost Efficiency / Time-to-value / Execution Risk / Market
    Opportunity / Evidence Quality + Recommended Scenario — `strategy.py:2492`). That
    default is a legit fallback, but the agent shouldn't land there for a multi-option
    request. Fix = strengthen the prompt / add a guard so multi-idea always batches;
    consider auto-proposing a rubric instead of silently using the default.
B2. **Uploads mis-routed by file type.** `JaspenChat.jsx:845 isChatAttachmentFile` only
    treats image/PDF/Word as chat attachments. Excel/CSV/PPTX/txt go to the SEPARATE
    `analyzeUploadedFiles` path and are NEVER attached to the agent convo → agent says
    "I don't see a file" + returns an unrelated analysis. Fix = route all supported
    types to the agent (or at minimum hand the agent the extracted text + a clear note
    of what was uploaded). Also surface which path a file took in the UI.
B3. ✅ FIXED (52cf7cd, NEEDS DO DEPLOY) — word/data uploads persist a 4k text excerpt
    on the chat-history entry; replayed user turns re-inject it so follow-ups keep the
    file content without re-attaching. UI display unaffected.
B6. ✅ FIXED (d8e7bfe, frontend/Vercel) — streaming client now parseErrorResponse() on
    !resp.ok so a 402 fires the credits-exhausted billing modal + toast; chat bubble
    shows "You're out of thinking power…" (retry disabled) instead of the generic error.
    (Original note below.)
~~B6 (original).~~ **Out-of-credits shows a generic error, not a clear message.** VERIFIED 6/4: a Free
    account at 0% thinking power failed batch scoring with "Sorry — I hit an error"
    (the generic stream-error fallback) instead of "You're out of thinking power —
    add credits / upgrade." This misled us into chasing a code bug that wasn't there
    (Essential account scored all 10 fine). FIX: detect the credit-exhaustion response
    in the streaming/score path and surface a specific, friendly message + upgrade CTA
    (analyze_project already returns a 'Thinking power limit reached' payload — mirror
    that on the conversation/score-batch path so the chat shows it clearly).
B4. ✅ FIXED (4733fde, frontend/Vercel) — first attempt (d27ea3b) made it WORSE (nested
    overflow chain didn't bound → couldn't scroll past the fold). Redone with a `flow`
    prop on TradeoffView: workspace grows to content + the canvas (overflow:auto) scrolls
    the whole page; chat-inline keeps its fixed card. Also dropped the height:100% wrapper.
    POLISH (same commit): custom-block remove × is now subtle (13px, #cbd5e1, hover-darken).

B5b. ✅ FIXED (4471416, NEEDS DO DEPLOY) — real failure was the AGENT TURN (long
    pre-analysis + tool thrash → stream error), upstream of the scoring engine. Now:
    queue_scorecards caps to 5 ideas (stashes the rest in scorecard_queue_overflow),
    and the prompt makes the agent tell the user it scores 5 at a time + offer to
    continue with the next 5. Keeps the chunking fix below as defense-in-depth.
    TODO later: wire "continue" to auto-pull from scorecard_queue_overflow (today the
    agent re-queues the next 5 from context, which works but isn't guaranteed).
B5. ✅ FIXED (8035079, NEEDS DO DEPLOY) — `_generate_batch_scorecards` now chunks
    >5 ideas into sub-batches (same rubric), merges cards, re-derives tiers from global
    score bands, pads failed chunks with None to keep caller alignment. Remaining: a
    true all-ideas portfolio_summary (currently first chunk only); watch gunicorn
    timeout for very large sets (each chunk = 1 sequential LLM call).
~~B5 (original).~~ **10-idea batch scoring errors out ("Sorry — I hit an error").** Reproducible:
    upload 10 ideas, agent sets rubric + queues all 10 (B1 working), but scoring
    fails. Root cause (high confidence): `score_batch_queued` scores ALL ideas in ONE
    LLM call at `max_tokens=8000` (`strategy.py:2568`). 10 ideas × ~6 criteria +
    rationales overflows 8000 → truncated JSON → parse fails. 3–4 ideas fit (why
    morning worked). FIX = chunk into sub-batches (~5) against the SAME rubric and
    merge cards + portfolio_summary; do NOT just raise max_tokens (risks model output
    cap). Confirm with one server log line from `[score_batch_queued]`.
    Note: also handle partial failures gracefully (render the cards that DID score).

## DEFERRED FEATURE NOTE (LB intent, 6/4)
- **Choice-prompt pop-up (C.9):** when LB said "do the survey thing," she means a
  pop-up option box where the agent asks a question and the user can SELECT or type an
  answer (not chat-only Q&A). Build the choice-prompt primitive so the discovery survey
  uses selectable option boxes. Future — not a tonight item.

## NEXT SESSION — LB's punch list (2026-06-04, do these first)
> Connectors confirmed still working — nothing was deleted; the scoring rework tied
> into the existing bones, so uploads/connectors are intact. Verify, don't rebuild.
1. ✅ DONE (dd56d16 be / 1a37380 fe) — agent add-block via patch_scorecard.add_blocks
   (→ display_overrides.custom_blocks). PLUS workspace "+ Add block" is now an ELEMENT
   PICKER (Text / Callout / Quote); each block carries a `type`. Agent blocks default to
   text. (Element-picker = the "workspace tools" item on LB's 6/4 plan.)
2. ✅ DONE (00f83fb, frontend) — main /new chat jumps instantly to latest message on
   initial thread restore; Workspace sidebar chat already pinned to bottom.
3. ✅ BUILT (b69e6cc, NEEDS DO DEPLOY + credited account to verify) — choice-prompt
   primitive. Agent emits [[choice]]{json}[[/choice]]; shared ChoicePrompt.jsx parses +
   renders clickable option cards in BOTH /new (renderConversationMessage) and the
   workspace sidebar (chatHistory.map). Click → sends label (onSubmit/sendChat); Other =
   type your own; multi-select joins; only latest card interactive. Prompt instructs the
   agent to use it for small discrete-answer questions, one at a time. VERIFY: trigger a
   question with discrete options on each surface; confirm cards render + clicking answers.
   FOLLOW-UPS if needed: tune when the agent chooses to use it; consider a real tool
   instead of the text convention if reliability is shaky.
~~3 (original).~~ **AI-agent CHOICE PROMPTS in all chats** (= the C.9 choice-prompt primitive / the
   "survey pop-up"). CLARIFIED 6/4: LB means option boxes "like how you [Claude] are
   asking me this question" — the agent presents a question + selectable options (click
   to answer, or type your own), inside the chats. NOTE: the workspace sidebar +
   execution chats ALREADY share the same agent + tools as /new (Jaspen.chat →
   conversation/continue), so tool access is NOT the gap — the gap is this interactive
   choice UI. BUILD SPEC (needs credited account to verify the agent emitting it):
   - Backend: new tool `ask_choice(question, options:[{label, description?}],
     allow_multi?, allow_text?)`; surface it in the reply payload as a structured
     artifact (ride the existing mutations/artifact pipeline — see
     appendArtifactMessagesFromPayload / normalizeMutationResults in JaspenChat).
   - Prompt: during discovery, when the next question has discrete options, call
     ask_choice instead of prose (one question at a time). Keep prose fallback.
   - Frontend: render the choice as clickable option cards in BOTH renderers —
     JaspenChat (renderConversationMessage) AND the workspace sidebar's own
     chatHistory.map (JaspenWorkspace). Click an option → send its label as the next
     user turn; "Other" focuses the text input. Multi-select → send joined labels.
   - Verify on each surface: scorecard / trade-off / execution sidebar + /new.
4. **User-custom colors / theming** — let users specify their own brand colors in
   instructions + workspace so requested scorecards render in their palette (per-artifact
   theme override; carries into the visual + exports). Ties to C.10.
4. ✅ DONE (e1abaf4 fe / cbc95fd be, NEEDS DO DEPLOY for B+C) — custom accent color:
   (A) workspace color picker → display_overrides.accent_color → ring/label/recommendation
   /Build-Execution-Plan use it; (B) agent sets it via chat ('use our brand color #hex')
   through patch_scorecard.accent_color; (C) PDF score + Word heading honor it in exports.
   PPTX/XLSX still magenta (disabled in menu). Verify on credited account.
5. **(LB testing)** — LB will exercise the app and flag glaring issues to fix next session.
6. ✅ DONE (00f83fb, frontend) — shared <BackToJaspen> component on Execution plan,
   Admin, Scores, Team, Account; removed the bespoke per-page back buttons.
7. ✅ DONE (e8278ef, NEEDS DO DEPLOY) — traced: objective WAS persisted + passed to
   the batch scorer but never injected into the batch prompt (only the single-card path
   used it), so it had no effect on multi-idea scoring. Now injects an OBJECTIVE LENS
   into the batch prompt (tilts generic dims; respects custom-rubric weights). Verify on
   a credited account: same ideas under Cost vs Growth should shift scores/ranking.

## Reference docs
- `ARCHITECTURE_VISION.md` — the target model + principles.
- `STUDIO_BUILD_PLAN.md` — the compartmentalized build plan + decisions.
- `LEGACY_REMOVAL_LIST.md` — what to retire once the new path is proven.

## Exports — re-activation backlog (currently MVP: PDF + Word only)
- **PowerPoint (.pptx):** condense the scorecard to **1–2 slides** (currently spreads
  too far), then re-enable in the Download/Share menu (remove `disabled` flag in
  JaspenWorkspace.jsx).
- **Excel (.xlsx):** polish the grid (ideally the full trade-off comparison grid, the
  user's native format) + verify openpyxl deployed, then re-enable.
- **True sharing:** "Copy link" copies an access-gated URL today. Build real public/
  shared links (view without login) later.
