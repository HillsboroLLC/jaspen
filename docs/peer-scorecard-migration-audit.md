# Peer-Scorecard Architecture — Baseline/Variant Audit

> Produced on `feature/canonical-decision-record` (2026-07-10). Target
> principle: **every scorecard is a first-class, standalone decision artifact;
> trade-off analysis compares independent scorecards, not variants of a
> baseline.** The canonical Decision Record already stores scorecards as a flat
> peer list (`decision_records.py::_collect_peer_scorecards`), so new
> capabilities consume the peer shape from day one. This audit maps what still
> assumes the legacy baseline/variant model, for a future
> `feature/peer-scorecard-architecture` branch. Nothing here blocks the
> Decision Record foundation.

## Where the baseline/variant assumption lives

### Storage (the root)
- **Session store:** `session['result']` holds ONE privileged card (the
  "baseline"), with `_baseline_scorecard` and `scorecard_snapshots` embedded
  inside it. The first idea scored in a batch becomes this baseline
  (`score_batch_queued` in `strategy.py`: "first = thread baseline, the rest =
  scenario snapshots").
- **Scenarios store:** every subsequent card is persisted via
  `_create_scenario_record` as a "scenario" under the thread, with
  `td['baseline']` and `td['baseline_inputs']` duplicating the privileged
  card. Scenario records were designed for lever-delta what-ifs; batch scoring
  reuses them as a container for *independent options*, which is the core
  model mismatch.
- `strategy.py` contains ~330 references to baseline concepts; the dedicated
  resolvers (`_resolve_thread_baseline`, `_extract_baseline_inputs`,
  `_baseline_financial_value`) encode the hierarchy.

### Read paths
- `get_thread_bundle` reconciles the two stores back into a flat list at read
  time (the "Merge scenarios saved via create_as_version" block) — evidence
  that consumers already want peers and the hierarchy is pure storage debt.
- `_collect_completed_scores` (`/strategy/scores`) reads only the baseline's
  embedded snapshots and therefore under-lists batch variants (see
  decision-intelligence-deferred-followups.md item 3, corrected).
- `_scores_analysis_entries` explicitly filters out non-baseline results
  (`if result.get('source_scenario_id') or result.get('isBaseline') is False:
  continue`).

### APIs
- `/strategy/scores` rows carry `is_baseline`; deletion route addresses
  `<thread_id>/<snapshot_id>` where the baseline snapshot is special-cased.
- Scenario CRUD (`/threads/<id>/scenarios*`) doubles as variant storage.

### Frontend
- `isBaseline` handling in `JaspenWorkspace.jsx`, `JaspenChat.jsx`,
  `ScoreDashboard.jsx`, `Scores.jsx` — baseline merge logic on restore
  ("Always merge baseline into the snapshot list…"), baseline-labeled UI, and
  the Score dropdown's special Baseline entry.

### Prompts
- Scoring prompts are clean — no baseline concept is pushed to the model.
  (The word appears only in an objective keyword list and in tier vocabulary,
  both harmless.)

## Why it matters
- The N3-era "Scorecard mislabel" bug class, the `/scores` under-listing, and
  the double bookkeeping (`baseline` duplicated in two stores) all descend
  from this model. NEXT_STEPS C.8 ("storage swap to standalone artifacts")
  named the same root cause; `studio_artifacts` tables already exist as a
  candidate destination.
- Constitution Art. 20-21 make every scored option part of durable knowledge;
  a storage model that privileges one option structurally contradicts the
  peer-comparison product (Art. 9's "displayed parts equal computed parts"
  extends naturally to "listed artifacts equal stored artifacts").

## Recommended migration path (future branch, in order)
1. **Write path first:** batch + single scoring persist every card as a
   standalone artifact (studio_artifacts or a `scorecards` table keyed by
   thread), while ALSO writing the legacy shape (dual-write, feature-flagged).
2. **Read paths second:** point `get_thread_bundle`, `/scores`, exports, and
   the Decision Record assembler at the artifact store; keep legacy fallback
   for old threads (or backfill once).
3. **Frontend third:** delete baseline-merge logic; the Score dropdown lists
   peers; "Baseline" label retires (or becomes a user-pinned "status quo" tag,
   which is the honest version of the concept).
4. **Retire scenario-store dual use last:** scenarios return to their real job
   (lever-delta what-ifs on a single card), decoupled from option storage.
5. Delete `_resolve_thread_baseline`/`_extract_baseline_inputs` call sites as
   they orphan.

Estimated shape: one focused branch, backend-led, with the bundle endpoint as
the compatibility seam. The Decision Record assembler needs no changes — it is
already peer-native and becomes the first consumer of the clean model.
