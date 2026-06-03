# Jaspen — Next Steps

> Working punch list. Current state: the core loop works end-to-end in `/new` —
> talk → agent interviews you → deterministic scoring on YOUR criteria → cards +
> ranked trade-off render live, with connectors + disclaimer present. Backup/restore
> point: branch `backup/pre-studio-20260603`, tag `pre-studio-baseline`.

## A. Quick polish (start here next session)
1. **Richer trade-off insights** (the data already exists, just not rendered):
   surface in the trade-off view → the portfolio recommendation (commit/develop/
   monitor sequence), the **key differentiator** (which criterion separates the
   winner), and a one-line "wins on X / loses on Y" per option.
   Source: `score-batch` already returns `portfolio_summary`; each card has
   `tier`, `key_insights`, `key_considerations`. Wire into TradeoffView.
2. **Verify the "LinkedIn Ads" label fix** post-deploy (top idea was showing as
   "Scorecard" — patched in 1016022; confirm it sticks).

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
