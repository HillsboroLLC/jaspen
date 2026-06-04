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

## Reference docs
- `ARCHITECTURE_VISION.md` — the target model + principles.
- `STUDIO_BUILD_PLAN.md` — the compartmentalized build plan + decisions.
- `LEGACY_REMOVAL_LIST.md` — what to retire once the new path is proven.
