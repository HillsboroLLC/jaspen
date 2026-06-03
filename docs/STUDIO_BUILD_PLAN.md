# Jaspen "Studio" — Compartmentalized Build Plan

> A clean, self-contained rebuild of the idea-vetting flow, wired into the existing
> UI but with its own storage and code. Old code stays until the new path is proven,
> then we remove it (see `LEGACY_REMOVAL_LIST.md`). Restore point before any changes:
> git branch `backup/pre-studio-20260603` + tag `pre-studio-baseline` (commit 717afb7).

## Decisions locked (from product owner)
- **Theming:** default to the org/app theme; user can override colors per artifact.
- **Thread/bundle concept:** removed. It only existed to compare scores; with
  independent deterministic scores we don't need it. Replaced by a thin parent
  ("workspace") + standalone artifact rows.
- **Compartmentalize:** new DB table(s) + new module(s), separate from existing
  `strategy.py` / `ai_agent.py` storage. Wire to the current UI/UX. Remove old
  files only after the new path works. Keep a removal list.
- **Backup before changes:** done (branch + tag above).
- **Scope guardrail:** this is a tool for vetting *business/strategic ideas*. The
  agent stays productive on that, but politely declines unrelated personal chatter
  ("my shoelaces"). Don't inhibit AI productivity; do inhibit off-topic use.
- **Connectors + uploads are first-class:** the agent pulls data from connectors
  OR an upload to inform deterministic scoring.
- **Outputs are downloadable** as PDF / Excel / Word (and viewable in-app).
- **Execution plan** supports the administrative work of actually executing.

## The canonical flow
1. User brings **one idea or many**.
2. App scores **deterministically** using the user's criteria/variables + any
   connector/upload data. Same inputs → same score.
3. **Sidebar streams "what would raise confidence"** for the current scoring.
4. **Auto-generate the artifact** once it has enough info (no manual trigger).
5. **Generate several at once** if the conversation calls for it (one-pass).
6. **Auto-generate the trade-off** comparison.
7. User can **open any artifact in the workspace** to workshop it with the agent.
8. **Edits auto-save.**
9. User can **generate an execution plan** and use the interface to execute
   (admin support).

## New data model (additive — does not touch existing tables)
- **`workspaces`** (thin parent; replaces the thread/session blob):
  `id, user_id, org_id, title, rubric (json: criteria+weights+groups), theme (json),
   created_at, updated_at, archived_at`
  - The shared rubric/criteria/theme live here ONCE (no per-artifact duplication,
    no last-writer-wins blob clobbering).
- **`artifacts`** (the standalone, first-class items):
  `id, workspace_id, user_id, org_id, type (scorecard|comparison|execution_plan|document),
   name, data (json), theme (json, optional override), display_overrides (json),
   created_at, updated_at, archived_at`
  - Each idea = one `scorecard` row. Two near-identical ideas = two rows. No
    baseline, no scenarios. A `comparison` is its own row referencing scorecard ids.
  - **Atomic per-row saves** → the clobbering class of bug is gone.

## New code (compartmentalized)
- `backend/app/models_studio.py` — the two SQLAlchemy models above.
- `backend/app/routes/studio.py` — new blueprint `/api/v1/studio/...`:
  - `POST /workspaces` (create), `GET /workspaces/:id` (load workspace + artifacts)
  - `PUT /workspaces/:id/rubric` (set/replace rubric+groups+theme)
  - `POST /workspaces/:id/score` (1..N ideas → one-pass deterministic scorecards)
  - `POST /workspaces/:id/compare` (trade-off artifact over chosen scorecards)
  - `PATCH /artifacts/:id` (reword / re-score / restyle — auto-saved)
  - `POST /artifacts/:id/execution-plan`
  - `GET /artifacts/:id/export?format=pdf|xlsx|docx`
- `backend/app/services/scoring.py` — the deterministic engine, lifted clean
  (weighted sum + confidence caps + groups), reused by the routes.
- `backend/app/prompts/studio_prompts.py` — focused agent prompts (scope guardrail,
  deterministic-scoring contract, auto-generate behavior, confidence insights).
- `frontend/src/studio/...` — new components, mounted into the existing workspace
  shell so the UX is continuous.

## Migration / ops (privileged steps run by the owner, not the agent)
- New tables are **additive**; existing data is untouched. Still:
  1. **DB backup first** (owner runs): `pg_dump "$DATABASE_URL" > ~/jaspen_pre_studio_$(date +%F).sql`
  2. **Create tables**: Alembic migration (preferred) or a one-off
     `db.create_all()` for the two new models. Agent writes it; owner applies it.
  3. **Deploy** as usual (owner): pull + restart gunicorn.
- **SSH / server access:** we do NOT need to expand the agent's access. Safer
  division of labor (and what we've been doing): the agent writes all code +
  migrations + exact commands; the **owner runs anything that touches prod**
  (migrations, backups, deploys). Keeps a human in the loop for prod — correct
  posture pre-launch.

## Build phases
- **P1:** models + `db.create_all` migration + `studio.py` create-workspace,
  set-rubric, one-pass score. Verify rows persist independently (no blob).
- **P2:** compare artifact + sidebar confidence insights + auto-generate.
- **P3:** workspace open/edit (auto-save) + execution plan.
- **P4:** exports (PDF/Excel/Word) + theming.
- **P5:** connectors/uploads feed scoring.
- **P6:** remove legacy (see `LEGACY_REMOVAL_LIST.md`).

## Open questions (to confirm before P1)
1. **Workspace grouping:** OK to keep a thin `workspace` parent (holds shared
   rubric/theme), or do you want artifacts fully standalone with the rubric copied
   onto each? (Recommend: thin parent — one rubric, no duplication.)
2. **Org theme source:** where does the default org theme live today (is there an
   org settings record we read colors from)?
3. **Auto-generate trigger:** what's "enough info to auto-generate"? Proposed:
   when criteria + at least one idea are present and the user hasn't said "wait."
