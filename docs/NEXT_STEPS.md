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

## 🔴 BUGS FOUND IN 6/4 PM TEST (triage first — diagnosed, not yet fixed)
> Root finding: there is ONE codebase / ONE deploy. The "two experiences" were the
> SAME code taking two different agent paths, not an old vs new version.
B1. **Agent reliability — falls into the single-card generic fallback.** When the user
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
B3. **Attachments are per-message only.** Once the user sends a follow-up without
    re-attaching, the model no longer has the file (no persisted attachment in the
    replayed history). Decide: persist last upload's extracted text into thread context
    so follow-ups can reference it.
B4. **Workspace page won't scroll.** Canvas scrolls (`JaspenWorkspace.jsx:1408`) but the
    stacked-ideas block is a short fixed-height box — only the inner box scrolls, page
    can't reveal more. Fix the nested overflow/height so the whole page scrolls.

## NEXT SESSION — LB's punch list (2026-06-04, do these first)
> Connectors confirmed still working — nothing was deleted; the scoring rework tied
> into the existing bones, so uploads/connectors are intact. Verify, don't rebuild.
1. **Agent add block** — let the AI add scorecard sections via chat (mirror the
   user-facing "+ Add block" in JaspenWorkspace.jsx; agent writes to `custom_blocks`).
2. **Workspace chat starts at the BOTTOM, not the top** — auto-scroll the workspace
   chat panel to the latest message on open (main + sidebar chats).
3. **AI-agent options function in ALL chats** — wire the agent option-boxes/tools into
   the main chat AND the sidebar chats in the workspace, INCLUDING the execution
   workspace (not just the primary /new chat).
4. **User-custom colors / theming** — let users specify their own brand colors in
   instructions + workspace so requested scorecards render in their palette (per-artifact
   theme override; carries into the visual + exports). Ties to C.10.
5. **(LB testing)** — LB will exercise the app and flag glaring issues to fix next session.
6. **Unify "Back to Jaspen" link across ALL pages** — adopt the workspace-page version
   of the "Back to Jaspen" link on every non-primary-interface page, and REMOVE any
   other back-to-Jaspen buttons/links so there's exactly one consistent control.
7. **Primary objective tags actually work** — LB can't tell from the UI if they do.
   Claude must TRACE end-to-end: where the primary objective is set, whether it's
   persisted, whether it's passed into scoring/the rubric, and whether it visibly
   affects the scorecard output. Investigate (not just visually verify) + fix.

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
