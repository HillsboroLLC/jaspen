# Jaspen — Architecture Vision & Target Model

> Working alignment doc. Captures the product principles and the target
> architecture so we stop accreting complexity and refactor toward one coherent
> model. Cities/GridPoint are only a *test fixture* — nothing is built around them.

## 1. Product principles (the north star)

1. **Generic.** Any set of ideas — products, vendors, campaigns, hires, markets,
   cities — produces a smart, organized output. No vertical-specific logic.
2. **Smart artifact generation.** The AI produces polished, well-structured
   artifacts (scorecards, comparisons, plans, documents) — like Claude artifacts /
   Manus / Lovable.
3. **Deterministic, consistent scoring.** Generation is flexible; the *scoring
   math is fixed and reproducible.* Same inputs → same score, every time.
   AI = judgment per criterion. Code = the arithmetic.
4. **Standalone artifacts.** Every idea/scorecard is first-class and independent.
   Two ideas that differ by one variable are **two separate cards**, not a base
   case and a tweak. **No "baseline," no "scenarios," no "adopted" hierarchy.**
5. **Conversational modification in the workspace.** The user refines an artifact
   by talking to it ("tighter," "swap the axes," "use our brand colors,"
   "re-score with a bigger budget"). The workspace edits the artifact in place.
6. **Theming (future).** Enterprise brand colors / templates on generated docs.
   Deferred, but the artifact model should carry a `theme` from day one.

**One-line mental model:** *An artifact studio for decisions* — describe ideas +
criteria → get standalone, deterministically-scored artifacts → refine them by
talking to them → compare → (later) theme and export.

## 2. Subsystems: keep vs. change

### A. Scoring engine — KEEP (this is the good part)
- AI assigns a 0–100 per criterion **with a rationale (put/take)**; Python computes
  the weighted total deterministically (`_recompute_jaspen_score`), applies
  confidence caps, derives category/tier.
- Rubric is generic over arbitrary criteria, with optional **groups** (e.g. Impact
  vs Fit) → per-group sub-scores.
- One-pass batch generation scores N ideas in a **single** model call (the "build
  the Excel" move) → no per-idea timeouts.
- **Principle to hold:** the model never does the final arithmetic; code does.

### B. Artifact model — CHANGE (this is the complexity to kill)
- **Today:** `session['result']` = a *baseline* scorecard; additional cards are
  *scenario records* in a separate store; `adopted_scenario_id`, `isBaseline`,
  snapshot assembly all hang off this. It's a scenario-modeling paradigm.
- **Target:** a **flat collection of standalone artifacts** on the thread:
  `thread.artifacts = [ {id, type, name, data, created_at, theme, display_overrides}, ... ]`
  - Types: `scorecard`, `comparison` (trade-off), `execution_plan`, `document`…
  - Each artifact is self-contained and equal. No baseline. No scenarios.
  - A trade-off/comparison is **its own artifact** that references a set of
    scorecard artifacts (or is regenerated from them).

### C. Generation flow — MOSTLY KEEP
- Agent gathers criteria + ideas, then calls generation. Single idea = the engine
  with N=1; many ideas = one-pass batch. Output = standalone artifacts appended to
  the flat collection.
- Readiness gate is already removed (confidence is informational, never a gate).

### D. Conversational modification — KEEP + generalize
- Any artifact can be edited by talking to it: **reword** (no score change),
  **re-score** (deterministic recompute of that artifact), **restructure**,
  **restyle/theme**. Scoped to the artifact the user is viewing/referencing.
- This largely exists (`patch_scorecard`, rescore) — it just needs to operate on
  the flat collection instead of baseline/scenario.

### E. Rendering (workspace) — MAKE FULLY DATA-DRIVEN
- Cards/insights/trade-off render purely from artifact data + theme. No hardcoded
  dimension labels or sections. The "dossier" (groups, tiers, roles, portfolio) is
  just a richer scorecard artifact; the comparison is an artifact.

### F. Theming — FUTURE, but reserve the slot
- Each artifact carries a `theme` (palette/brand). Enterprise sets a default;
  user can override conversationally. Applied at render + export.

## 3. What's making it "overly complicated" (prune list)
- **Baseline/scenario hierarchy** → replace with the flat artifact collection.
- **Full-payload-replace session storage** (one big JSON blob, last-writer-wins)
  → caused the rubric/queue clobbering bugs. Move artifacts to an append-friendly
  store (per-artifact rows or atomic appends) so writers don't stomp each other.
- **Hardcoded dimension labels/sections in the UI** → data-driven from the rubric.
- **Naming** that leaks the old model ("baseline," "scenario," "adopted") → drop.

## 4. Migration path (here → there) without breaking launch
The risk: baseline/scenarios is load-bearing (bundle, trade-off, execution plans).
So phase it behind a flat collection rather than ripping it out:

- **Phase 1 — Introduce the flat collection as source of truth.**
  New scorecards are written as standalone artifacts in `thread.artifacts`. The
  thread bundle assembles its snapshot list from `artifacts` first, falling back
  to legacy baseline/scenarios for old threads. No UI change yet.
- **Phase 2 — Point readers at the collection.**
  Trade-off/comparison and execution-plan attach to artifacts by id (not baseline/
  scenario). UI renders from the collection.
- **Phase 3 — Stop writing baseline/scenarios.** Remove the hierarchy + naming.
- **Phase 4 — Storage hardening.** Per-artifact persistence (atomic appends) so the
  full-payload-replace clobbering class of bug is gone for good.

Each phase is independently shippable and reversible.

## 5. Open questions to align on
1. **Artifact granularity.** Is a "scorecard" one idea (one card), and a
   "comparison" a separate artifact over many cards? (Proposed: yes.)
2. **Single source of truth for a comparison** — does it store its own snapshot of
   the cards, or always recompute from the live cards? (Proposed: recompute; cards
   are the source of truth.)
3. **Theming scope** — per-artifact, per-thread, or per-org default? (Proposed:
   per-org default, per-artifact override.)
4. **Sequencing** — do Phase 1 now (foundational), or finish verifying the dossier
   on current storage first, then Phase 1? 

---
*Status: draft for alignment. No app code changes implied by this doc.*
