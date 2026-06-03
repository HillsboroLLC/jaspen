# Legacy Removal List

> Files/areas the new "Studio" path supersedes. **Do NOT delete until the new path
> is proven and agreed.** This is the checklist for the final cleanup phase (P6).
> Restore point: branch `backup/pre-studio-20260603`, tag `pre-studio-baseline`.

## How to use
When the Studio version of a capability is built and verified, check the legacy
item and note the replacement. Remove only after everything below is checked and
the new path has run in production without the old code.

## Backend
- [ ] `backend/app/routes/sessions.py` — session blob storage (`load_user_sessions`,
      `save_user_sessions`, full-payload upsert). → replaced by `workspaces` +
      `artifacts` tables (`models_studio.py`).
- [ ] `backend/app/routes/strategy.py` — thread/bundle + baseline/scenario logic:
      `get_thread_bundle`, `_scorecard_snapshot_state`, `_create_scenario_record`,
      `_resolve_thread_baseline`, scenario CRUD routes. → replaced by `studio.py`
      standalone-artifact routes. (Keep `_recompute_jaspen_score`,
      `_generate_jaspen_scorecard`, `_generate_batch_scorecards` — move into
      `services/scoring.py`.)
- [ ] `backend/app/routes/ai_agent.py` — baseline/scenario-coupled pieces:
      `generate_scorecard` baseline-vs-scenario branch, `queue_scorecards` +
      `/score-next` + `/score-batch` (interim), bundle-dependent persistence.
      → replaced by studio one-pass score + artifact patch.
- [ ] "baseline" / "scenario" / "adopted" naming throughout. → gone.

## Frontend
- [ ] `frontend/src/jaspenInterface/Workspace/JaspenChat.jsx` — bundle hydration,
      `refreshBundle`, baseline/scenario state, drain loop. → replaced by
      `frontend/src/studio/...` wired into the same shell.
- [ ] `frontend/src/jaspenInterface/Workspace/JaspenClient.jsx` — `getThreadBundle`,
      scenario endpoints, `scoreNext`/`scoreBatch` (interim). → studio client.
- [ ] `frontend/src/jaspenInterface/Workspace/TradeoffView.jsx` — if it depends on
      scenario/baseline shape; otherwise adapt to artifact shape.

## Notes
- The deterministic scoring engine and the rubric/groups model are KEPT (lifted into
  `services/scoring.py`), not removed.
- Items added during the interim one-pass work (`queue_scorecards`, `/score-next`,
  `/score-batch`) are scaffolding — superseded by the studio `/score` route.
