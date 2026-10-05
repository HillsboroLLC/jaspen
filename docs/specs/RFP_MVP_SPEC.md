# RFP Decision Kit: MVP Implementation Spec

Status: ready for implementation · Revision 4 (2026-10-04): follow-up decisions
7–10 applied (§7); amendments in Appendix A now applied to the governing documents · Revision 2 aligned the
spec to the Constitution and Framework · No product code was changed to produce this.

Code references are against current `main` (`ef9fb98c`, `codex/dev-baseline-prep`
worktree). Search by function name if a line number has drifted. Codex has
uncommitted stabilization work in that worktree; re-check references after it lands.

---

## 0. Constitutional frame

This spec adds **no new methodology**. The universal flow stays
**Discovery → Scoring → Trade-Off → Execution**, and the scoring engine (criteria
× weights × evidence × confidence → deterministic rollup) is unchanged.

RFP is delivered as a **Decision Kit**: a configuration that selects, labels and
pre-fills **general mechanisms**. Every mechanism in §2 works for any decision
type; RFP is just the first kit that uses them.

| Article | How this spec honors it |
|---|---|
| 1 · AI never does the math | Every score, metric, gate effect, verdict band, portfolio selection and schedule is computed in code (§2, §4). Agent prose may only cite numbers from canonical records or the user's own text (SI-1). |
| 2 · Criteria belong to the human | The kit *proposes* a starter rubric and gates. Nothing is saved until the user approves or edits it. Verdict thresholds are fixed, visible, versioned kit methodology constants (like category bands), and the human can override the recommendation when recording the decision (G5). |
| 4 · Jaspen prepares, humans decide | Jaspen shows a *recommended* verdict. Only the user records Bid / Bid with conditions / No-Bid through the existing decision record (`record_final_decision`). |
| 5, 10 · Facts move scores, holistically | Covered by integrity requirements SI-3 and SI-4. |
| 6 · Same inputs, same outputs | SI-2: identical inputs return the stored result and the model is not re-run. Changed facts or assumptions trigger holistic re-scoring. |
| 7 · Caps enforced in code | Confidence caps untouched. Gates never raise a score. |
| 9 · Every number decomposes | The verdict, metrics, gates and portfolio choice each show their full derivation on the card and in exports (G5, SI-5). |
| 12 · Null over fiction | Missing fields stay empty and are labeled. Metrics with missing inputs show "—", never a guess. |
| 13, 14 · Confidence never gates | Scoring runs whenever the user asks, at whatever confidence the evidence supports. Required fields are prompts, not blockers. |
| 15, 16 · One question, never block | At most one or two missing-field questions per turn, never in a blocking modal. |
| 18 · Plans are derived | Every plan task carries lineage to a specific decision element: weak criteria, named risks, recommendations, and (per the drafted amendment in Appendix A) recorded conditions, gates, requirements and recorded commitments. No fixed workstream templates. Failure offers Retry only, with no fallback plan (G7). |
| 19 · Form, never content | RFP lives entirely in kit configuration (§3). Kits cannot alter caps, rollup, categories, patch-vs-rescore rules or plan-derivation rules. |
| 20 · Decisions become records | Verdict, conditions and gates are saved into the canonical decision record. |

### What a Decision Kit may and may not do

| A kit **may** | A kit **may not** |
|---|---|
| Define structured option fields (names, types, labels) | Change confidence caps, the rollup formula or category bands |
| Propose a starter rubric and gate suggestions, for the user to approve | Save criteria, weights or gates the user hasn't approved |
| Pick metrics from the code metric library and label them | Introduce model-computed numbers or new arithmetic outside the library |
| Supply verdict vocabulary and **versioned verdict thresholds** (fixed methodology constants, always visible) | Hide a threshold, let a user or session edit it, change it without a version bump, or let a verdict bypass the gate/score/confidence rule |
| Choose which fields and metrics appear as trade-off columns | Change ranking math or override a human Strategic Necessity lock |
| Name which fields hold the plan deadline and requirement lists | Add plan tasks that have no lineage to the decision |
| Supply prompt hints for the interviewer (which facts matter) | Add a second persona or change the patch-vs-rescore rule |

### Prerequisites (from the current stabilization pass)

| Prerequisite | Why |
|---|---|
| Execution planner app-context fix | G7 depends on the AI planner actually running |
| Agent reads every scorecard in the thread | Trade-off, portfolio and verdict explanations need all options |
| Removal of the `proactive_next_step` template, chat cards refreshed by id, one score scale | Consistency groundwork for SI-5 |
| Batch auto-continue; no leaked orchestration text | Kits routinely compare 5–12 options |
| **Re-score target guard (SI-6)** | The re-test showed a re-score overwriting a different option's record. This must land before any RFP work. |

---

## 1. Data model (JSON only, no migration)

All additions live in existing JSON columns: the `user_sessions.payload`
session blob, `Scorecard.data`, `scenarios_json`, and `decision_records.record`.
**No Alembic migration.** (SI-5's canonical-record work may need an index; see SI-5.)

### 1.1 Thread level

```jsonc
"decision_kit": null | "rfp_bid" | "rfp_vendor_selection",   // null = general
"decision_kit_version": 1,
"decision_kit_source": "user" | "suggested_accepted",
"kit_context": {                    // kit-defined thread facts, same provenance format as option fields
  "constraints": [                  // used by G6; general shape
    {"key": "max_selected", "label": "Pursuit capacity", "value": 3, "source": "user"},
    {"key": "cap_contract_value", "label": "Bonding headroom", "value": 60000000, "unit": "USD", "source": "user"}
  ],
  "decision_deadline": {"value": "2026-11-14", "source": "user"}
}
```

Verdict thresholds are **not** stored per thread. They live in the kit config as
versioned methodology constants (§3), and each recommendation records the
version and values it used (§1.2).

### 1.2 Option level (on each queued idea and each scorecard)

```jsonc
"option_key": "opt_7f3a…",          // stable option identity, assigned at queue/create time (SI-6)
"attributes": {                     // G2: kit-defined fields, generic storage
  "<field_key>": {"value": …, "source": "user" | "document" | "calculated" | "assumed",
                  "evidence": "verbatim quote or doc ref", "updated_at": "…"}
},
"metrics": {                        // G4: code-calculated only
  "<metric_key>": {"value": 425250, "formula": "expected_value", "inputs": {…}, "inputs_assumed": ["margin_pct"]}
},
"gates": [ {"key": "…", "label": "…", "rule": "…", "status": "pass" | "fail" | "unknown",
            "evidence": ["verbatim quote"], "basis": "…"} ],
"recommendation": {                 // G5: the decomposable recommended verdict
  "verdict_key": "advance" | "advance_with_conditions" | "decline",
  "label": "Bid with conditions",   // from kit vocabulary
  "trace": [ {"step": "gate", "key": "comparables", "status": "unknown", "effect": "conditional"},
             {"step": "score", "value": 48, "threshold": 60, "effect": "below advance"},
             {"step": "confidence", "value": 58, "threshold": 55, "effect": "meets"} ],
  "conditions": [ {"id": "cond_1", "text": "Confirm JeffCo scores 2 of 3 comparables as partial",
                   "origin": {"type": "gate", "key": "comparables"}, "due_by": "2026-10-24",
                   "due_by_rule": "earliest(questions_due, decision_deadline − 10 business days)"} ],
  "thresholds_used": {"kit": "rfp_bid", "version": 1, "advance_min_score": 60,
                      "decline_below_score": 45, "min_confidence_pct": 55, "close_call_margin": 5},
  "computed_at": "…"
}
```

### 1.3 Rubric schema (general)

`scoring_rubric.criteria[]` keeps `key, label, weight, is_risk, group, description`
(`set_scoring_rubric`, `ai_agent.py`). Add `gate: bool` and `gate_rule: str`.
Gates are excluded from weight normalization. A rubric records
`approved_by_user_at`. Scoring with a proposed-but-unapproved rubric is allowed
only after the user explicitly says "score" (Article 13), and the card then
notes "Rubric proposed by Jaspen, not yet edited".

### 1.4 Plan task lineage (general, used by G7 and the sync spec)

```jsonc
"lineage": [ {"type": "condition" | "gate" | "requirement" | "weak_criterion" | "risk" | "recommendation" | "decision_commitment",
              "ref": "cond_1" | "<criterion key>" | "<risk id>" | "<attribute key>[i]" | "<decision record id>",
              "label": "human-readable source"} ]
```

### 1.5 Decision record

Reuse `decision_records` (`decision_type`, `final_decision`, `status`,
`decided_at`, `record` JSON). When the user records a verdict:
`decision_type = decision_kit`; `record.kit_verdict = {verdict_key, label,
option_key, scorecard_id, recommendation_snapshot, conditions_accepted[], override_reason?}`.
The recommendation snapshot (including its trace and thresholds) is stored so
the record shows what Jaspen recommended and what the human decided.

---

## 2. General mechanisms (core, domain-neutral)

Each mechanism is built once and used by any kit. Nothing here mentions RFPs.

### G1. Decision Kit registry and thread selection · P1 · M

**Behavior**
- `backend/app/decision_kits/` holds a registry (`registry.py`) plus one
  declarative config file per kit (`rfp_bid.py`, `rfp_vendor_selection.py`).
  A kit config is **data only**: field schema, starter-rubric proposal, gate
  suggestions, metric selections (keys into the G4 library), verdict vocabulary,
  **versioned verdict thresholds** (`verdict_thresholds: {version, …}`; any change
  requires a version bump and a changelog line in the kit file), trade-off column
  selection, plan-derivation bindings (G7), and interviewer hints. A schema validator rejects any kit
  config containing executable logic or overrides of protected settings (caps,
  rollup, category bands, derivation rules).
- **Thread selection:** a "Decision kit" row in the composer footer, separate
  from the objective chips (`JaspenChat.jsx` `renderObjectiveTags`, ~7036):
  **General** (default) · **RFP response (Bid / No-Bid)** · **RFP vendor
  selection**. The objective lens (`strategy_objective`) is unchanged and combines
  with any kit.
- **Suggestion, never auto-switch:** the agent may offer one choice chip ("Use
  the RFP decision kit?") when the message clearly describes an RFP. Accepting
  sets `decision_kit_source: "suggested_accepted"`.
- **Changing kit after scoring:** confirm, then re-score holistically (SI-4).
  Fields entered so far are kept.

**Code areas:** new `decision_kits/` package; `ai_agent._new_session`;
`PATCH /threads/<id>` (`ai_agent.update_thread`, ~11621) accepts `decision_kit`
(and rejects any attempt to set thresholds); `_build_agent_system_prompt` (~3163)
appends the kit's interviewer hints in Jaspen's voice. Frontend selector, thread
header chip ("RFP response · Balanced"), `JaspenClient.setThreadDecisionKit`.
Layer: both + prompt. **Migration: no.**

**Acceptance**
1. Selecting a kit persists across reload. The objective selection is independent.
2. A General thread's system prompt and scoring payload are byte-identical to today (snapshot test).
3. The kit validator rejects a config that sets confidence caps, rollup weights
   or a task-template list, or changes `verdict_thresholds` values without
   incrementing its version (unit tests).
4. Accepting the suggestion chip sets the kit. Ignoring it changes nothing.

### G2. Structured option fields · P1 · M

**Behavior**
- Kit-defined fields stored in `attributes` with provenance (§1.2). A general agent
  tool, `set_option_attributes(option, fields)`, writes only values present in the
  user's words or uploaded documents (`source: "user"` / `"document"`, with
  `evidence`). It never writes a number the user didn't state. Exempt from the
  per-turn mutation cap, like `set_scoring_rubric`.
- An **Option facts** card per option (sidebar Insights for the selected option;
  inline under new options) lists the kit's fields, editable in place. Empty
  fields are labeled with their role ("Used for scoring", "Used for the plan
  deadline"). Nothing blocks scoring.
- **Interviewing:** the agent asks for at most one or two missing high-value
  fields per turn, as choice chips where possible (Article 15). Saying "score"
  stops the questions (Article 13).
- `queue_scorecards` items carry `attributes` so batch scoring receives them.
- The intake baseline panel (`IntakeReceipt.jsx`, `decision_impact` `GET /baseline/<thread_id>`)
  counts options, criteria and gates from these structures instead of showing 0.

**Code areas:** `ai_agent.py` tool schema next to `set_scoring_rubric` /
`queue_scorecards` (~5134, ~5585), `_MUTATION_TOOLS`, `_EXEMPT_MUTATION_TOOLS`.
Pass attributes into `_generate_jaspen_scorecard` (~2822) and
`_generate_batch_scorecards` (~3260) as structured facts. `routes/decision_impact.py`.
Frontend `OptionFactsCard`. Layer: both + prompt. **Migration: no.**

**Acceptance**
1. A field with `source: "user"` always has an `evidence` quote found verbatim in
   the user's text (reuses the existing evidence-verification helper).
2. In a 7-option message, every extracted value is attached to the correct option (fixture test).
3. Editing a field marks the scorecard "Facts changed: re-score?" and does not move the score until re-scored (SI-3, SI-4).
4. The intake panel shows the correct option and criteria counts.

### G3. Gates (pass/fail criteria) · P1 · M

**Behavior**
- A gate is a rubric criterion with `gate: true`. Gates are **proposed** (from the
  kit's suggestions and from requirement fields) and become active only when the
  user approves them in the rubric. The rubric shows them as a "Must-haves" group.
- Scoring grades each gate `pass` / `fail` / `unknown` with verbatim evidence.
  Post-processing in code enforces these rules:
  - `pass` requires medium or high evidence. The same calibration as
    `_calibrate_confidence_to_verified_evidence` applies.
  - Anything assumed becomes `unknown`.
  - `fail` requires an explicit supporting statement.
- **Gates never change the weighted score** (Article 7: they cannot raise it, and
  they don't silently lower it). They affect only the recommended verdict (G5)
  and the display: a failed gate shows a banner naming the gate and its evidence.

**Code areas:** `set_scoring_rubric` (~5640) accepts `gate`/`gate_rule` and
excludes gates from normalization; the scoring prompts emit `gates[]`; a gate
post-processor next to the evidence calibration; `_recompute_jaspen_score`
(~2677) ignores gate criteria. Frontend gate chips and banner. Layer: both +
prompt. **Migration: no.**

**Acceptance**
1. The weighted score is identical with or without gates in the rubric (unit test).
2. A gate cannot be `pass` on assumed evidence (unit test on the post-processor).
3. A gate proposed by Jaspen is inactive until the user approves it.
4. The gate's status, evidence quote and rule are visible on the card and in exports.

### G4. Deterministic metric library · P1 · S

**Behavior**
- A code library of named, pure formulas. Kits select and label them; kits cannot
  define new arithmetic. MVP formulas:
  - `expected_value` = value × probability × margin
  - `ratio` = a ÷ b (used for pursuit ROI)
  - `per_unit` = a ÷ quantity (e.g. expected value per FTE-week)
  - `sum` (across options, for G6)
  - `difference` (for runner-up comparisons)
- Each result stores its formula, its inputs (with their provenance) and any
  assumed inputs. Missing input → `null` with "Add <field> to calculate".
- Metrics render on the card ("Economics" strip, kit-labeled), in the trade-off
  table, in exports and in the agent context. The agent cites them; it never
  computes them (SI-1).
- `_remove_unverified_model_numbers` (`strategy.py` ~2540) keeps `attributes.*`
  and `metrics.*` because they carry provenance, and keeps stripping
  model-authored numbers everywhere else.
- Scoring receives metrics as stated facts for the relevant criterion. The model
  judges the criterion; it does not do the math.

**Code areas:** new `backend/app/decision_metrics.py` (pure + unit tests), invoked
after attribute writes and in `_normalize_scorecard_payload` (~959). Frontend
economics strip. Layer: both. **Migration: no.**

**Acceptance:** SI-9. Also: $42M × 22.5% × 4.5% = $425,250. ROI with an $85K
pursuit cost = 5.0×. A missing margin shows "—". Every metric shows "Calculated
from: …" on hover or expansion.

### G5. Decomposable recommendation and human-recorded verdict · P1 · M

**Behavior**
- A **deterministic rule** turns gates, the score, confidence and the kit's
  versioned `verdict_thresholds` into a recommendation. The kit supplies only
  labels and those constants.
  - Any gate `fail` → `decline`.
  - Else, score < `decline_below_score` → `decline`.
  - Else, all gates `pass` and score ≥ `advance_min_score` and confidence ≥
    `min_confidence_pct` → `advance`.
  - Otherwise → `advance_with_conditions`.
- **Conditions** are generated from structured sources only: each `unknown` gate,
  each threshold not met (e.g. "Confidence 48% < 55%: strengthen evidence on
  <lowest-confidence criterion>"), and each `what_would_improve` item the model
  attached to a criterion that blocks `advance`. Condition text may be
  model-worded, but its origin, threshold and due date are code-assigned.
- **Traceability on the card and in exports:** a "Why this recommendation"
  panel lists every trace step (gate results with evidence, score versus
  threshold, confidence versus threshold), the thresholds used with their kit
  name and version ("RFP response kit v1: Bid at ≥ 60, No-Bid below 45, minimum
  confidence 55%"), and each condition's origin. Nothing contributes that isn't shown.
- **Thresholds are fixed methodology constants** (owner decision 1). They're
  visible and versioned but can't be edited per thread or per user. Changing them
  means shipping a new kit version. A recommendation is never silently recomputed
  under a new version: it keeps the version it was computed with, and moves to the
  new one only when the option is re-scored or the user chooses "Recompute
  recommendation under kit v2". That recompute is deterministic code with no model
  call (it re-applies the new thresholds to the stored gates, score and
  confidence) and is logged. If the facts or evidence changed since the stored
  result, the action is a normal holistic re-score instead (SI-4).
- **The human's lever is the decision, not the threshold:** the user can record a
  verdict different from the recommendation (see below).
- **Human decision:** the card offers "Record decision" with the kit's labels
  (Bid / Bid with conditions / No-Bid; buyer: Select / Shortlist / Eliminate).
  It uses the existing decision record (`POST /decision-records/from-thread/<thread_id>`
  → `record_final_decision`). Choosing differently from the recommendation asks
  for a one-line reason. Language always reads "Jaspen recommends", never
  "Jaspen decided" (Article 4).
- The chat summary may only restate the computed recommendation (it receives it
  as a fact) and may not introduce a different verdict.

**Code areas:** new `backend/app/decision_recommendation.py` (pure + tests),
called in normalization. `decision_records.py` create/decide paths store
`kit_verdict`. Frontend recommendation panel (read-only thresholds with kit
version), record buttons
(`RecordDecisionPanel.jsx` presets). `scorecardPdf.js`, `routes/export.py`,
`decision_report.py`. Layer: both. **Migration: no.**

**Acceptance**
1. JeffCo (score 48, comparables gate unknown, confidence 58%) → "Bid with conditions".
   The trace shows: gate unknown → conditional; 48 < 60; 58% ≥ 55%. The condition
   cites the comparables gate and a due date with its rule.
2. No API or UI path edits thresholds (`PATCH` attempts are rejected). Shipping
   kit v2 with different thresholds leaves existing recommendations on v1 until
   re-score or explicit recompute, and the trace shows the version used.
3. The PDF contains the same trace, thresholds and conditions as the card.
4. Recording a verdict different from the recommendation requires a reason. The
   decision record stores both the recommendation snapshot and the human verdict.
5. The chat text never names a verdict different from the computed one (integration test).

### G6. Constraint-based selection · P2 · M

**Behavior**
- When `kit_context.constraints` hold numeric limits (count, sum of an attribute
  or metric), code computes the best selection: exhaustive search for n ≤ 12,
  maximizing the sum of the kit-selected objective metric (tie-break: weighted
  score). Gated-out options are excluded.
- Output: best set, runner-up, the differences (Δ objective, Δ each constraint),
  excluded options with reasons, and each constraint's slack. All of it is visible
  and decomposable.
- **Human locks are respected (Article 3):** options the user marks
  Strategic Necessity are always included, and the optimizer fills the remaining
  capacity. Pin and exclude controls recompute instantly.
- The agent gets the result through a read-only tool and quotes it (SI-8).

**Code areas:** new `backend/app/decision_selection.py`; agent tool;
`POST /strategy/threads/<id>/selection`; `TradeoffView.jsx` panel.
Layer: both. **Migration: no.**

**Acceptance:** SI-8. Also: a locked option is always included; pin and exclude
recompute; no constraints → panel hidden.

### G7. Derived execution plans with failure disclosure · P1 · M/L

**Behavior** (general; the kit supplies only field bindings, §3)
- **Trigger:** after the user records an advancing verdict (G5), or via the
  existing "Build Execution Plan" on any scorecard. For a kit thread whose verdict
  isn't recorded yet, the dialog offers "Record decision first" and doesn't
  generate a plan on its own.
- **Lineage sources** (Article 18, including the drafted amendment in Appendix
  A, approved in owner decision 5). The planner is given only these, assembled in
  code, each with an id:
  1. recorded conditions (G5)
  2. failed or unknown gates
  3. requirement fields (the attributes the kit binds as requirement lists)
  4. weak criteria (< 75, per the Framework's existing remediation rule)
  5. named top risks
  6. recommendations
  7. the decision commitment itself (e.g. the recorded verdict and its deliverable,
     plus the deadline field the kit binds)
  8. the user-provided team (names, roles, optional emails, from the roster or a
     one-question pre-flight)
- **Every task must cite at least one lineage id.** Code validates the planner
  output: tasks without valid lineage are dropped, and if fewer than the lineage
  items require are left, generation counts as failed. Phases are groupings of
  the derived work, named from the content. Per the amended Framework §4.2
  (Appendix A, owner decision 2), the familiar phase sequence and the 10–18 task
  range are **guidance only**. The planner may use them when they fit, but derived
  work takes precedence: a plan with 7 or 25 lineage-backed tasks is valid, and
  every lineage item must be covered.
- **No fixed workstream templates** in any kit, and no generic tasks ("Kickoff
  alignment", "User acceptance testing", "Training rollout") unless they trace to
  a lineage item.
- **Deadline and backward scheduling:** if the kit binds a deadline field, the
  commitment's delivery task is pinned to the deadline minus a user-visible buffer
  (default 1 business day). Dependent work is scheduled backward through
  `depends_on` in code (`_materialize_ai_wbs` gets a `deadline=` mode). Work
  that can't fit is reported as a **compression warning** with task names and
  shortfall. Nothing is silently scheduled past the deadline; tasks the user
  marks post-deadline (e.g. interview prep) are labeled as such.
- **Owners:** assigned from the provided team. Unmatched tasks stay "Unassigned"
  with a suggested role. Owners are never invented names.
- **Failure disclosure, Retry only** (owner decision 3): if the AI planner fails
  (provider error, invalid output, or lineage validation fails), **no plan is
  written**. The UI shows "Plan generation failed: <plain reason>. Your decision
  and its N source items are saved." with a single action, **Retry**. There is no
  generic, canned or draft fallback plan in the MVP. `_heuristic_wbs_suggestion`'s
  template is removed from every plan path (route and agent tool). The operation
  is recorded as failed, never succeeded or degraded-with-plan, and no credits are
  charged for a failed generation.
- **Lineage is visible:** each task shows "Derived from: <source label>" in the
  plan canvas, Excel export, and synced Jira/Smartsheet descriptions.

**Code areas:** `strategy.py` `generate_ai_wbs` route (~7196), pre-flight
(~7319; ask for team/deadline whenever missing in kit threads),
`_generate_ai_wbs_suggestion` (~5558: prompt receives lineage items and must
return lineage; remove the fixed phase-arc rule and the mandatory
change-management/value-capture tasks for lineage mode), lineage validator,
`_materialize_ai_wbs` (backward mode), `_heuristic_wbs_suggestion` (~5243,
retired from plan paths), `ai_agent.py` `generate_execution_plan` tool (same
rules). Frontend: failure state and actions, compression warning, lineage
labels in `JaspenExecutionCanvas.jsx` and `ExecutionPanel.jsx`, Excel export
column. Layer: backend + prompt + frontend. **Migration: no.**

**Acceptance**
1. JeffCo with a recorded Bid, one condition, the 30% small-business requirement,
   deadline 2026-11-14, and a team of six: every task has ≥ 1 valid lineage
   reference; the condition, the requirement and each weak criterion each map to
   ≥ 1 task; no task is due after 2026-11-14 unless marked post-deadline; ≥ 80% of
   tasks have a named owner from the team.
2. No task title matches the retired generic list unless it carries lineage.
3. A forced planner failure writes no plan, leaves any existing plan untouched,
   shows the failure message with Retry as the only action, logs the operation as
   failed, and charges no credits. No code path returns heuristic template tasks
   (grep test plus unit test).
4. A 3-day deadline produces a compression warning listing overrun tasks; nothing moves past the deadline.
5. A General-thread plan follows the same lineage rules (weak criteria, risks,
   recommendations), consistent with the Framework's existing §4.1 rules.
6. A lineage-valid plan outside the 10–18 range or the guidance phase sequence is
   accepted (guidance, not structure). A plan that leaves any lineage item
   uncovered is rejected.

### G8. Kit-aware trade-off presentation · P1 · M

**Behavior**
- `TradeoffView` columns, status labels and default quadrant axes come from the
  kit config. Statuses show the **recommended verdict** label (with "recommended"
  wording) or the **recorded** verdict once decided. This replaces the score-band
  statuses (`deriveStatus`, ~line 88: PRIORITIZE/HOLD/PARK) in kit threads.
  General threads keep today's behavior.
- Columns: kit-selected attributes and metrics (each with provenance on hover)
  and a gates summary.
- Gated-out options are muted and sorted last, with the failing gate shown.
- Close calls (top two within `close_call_margin`) are flagged, naming the
  largest weighted criterion gap and any unknown gates. This is code-derived.
- **Closing summary after multi-option scoring:** a deterministic summary
  (extending `_portfolio_summary_from_cards`, ~3216) lists the recommendation per
  option with its trace headline. The agent may add narrative, not a different
  ranking or verdict.
- The sidebar headline shows the selected or leading card from the canonical record (SI-5).

**Code areas:** `TradeoffView.jsx` (`deriveStatus`, `deriveIdeas`,
`resolveDimDefs`, `TableHeader`, `PortfolioRow`, `TradeoffQuadrant`),
`tradeoffInsights.js`, `strategy.py` summary. Layer: both. **Migration: no.**

**Acceptance**
1. Two-RFP scenario: Denver Health shows "Bid (recommended)" and CO DOR shows its
   computed recommendation. The table shows win %, contract value, expected value
   and pursuit effort with provenance. The closing summary appears without being asked.
2. ERP scenario: an option failing an approved gate is muted at the bottom with its gate.
3. A General thread's trade-off is visually unchanged (snapshot).

---

## 3. RFP Decision Kit configuration

Pure configuration over G1–G8. No RFP logic exists outside these kit files and their labels.

### K1. `rfp_bid` kit (responding to an RFP) · P1 · S (config) + review

| Config element | Content |
|---|---|
| Fields | `client`, `opportunity_ref`, `submission_due` (date), `questions_due` (date), `award_expected` (date), `contract_value` (money), `contract_term_months`, `award_method` (enum), `win_probability` (%) + `win_probability_basis`, `margin_pct` (%), `pursuit_cost` (money or FTE-weeks), `capacity_draw` (money/unit), `incumbent`, `competitors[]`, `relationship` (enum), `mandatory_requirements[]` |
| Metrics (from G4) | `expected_value(contract_value, win_probability, margin_pct)` labeled "Expected margin". `ratio(expected_value, pursuit_cost)` labeled "Pursuit ROI". `per_unit(expected_value, pursuit_cost[fte_weeks])` labeled "Expected margin per FTE-week" |
| Starter rubric **proposal** | Win probability & competitive position 20 · Financial attractiveness 20 · Delivery capability & capacity 20 · Qualifications & past performance 15 · Strategic fit & relationship 15 · Contract & commercial risk 10 (`is_risk`). The agent adapts labels to the facts and asks for approval or edits (Article 2). |
| Gate **suggestions** | One per `mandatory_requirements[]` item; "Able to submit by `submission_due`"; "Capacity/bonding available for `capacity_draw`". All need user approval. |
| Verdict vocabulary | advance → **Bid** · advance_with_conditions → **Bid with conditions** · decline → **No-Bid** |
| Verdict thresholds (**v1**, fixed methodology constants) | advance ≥ 60 · decline < 45 · minimum confidence 55% · close call 5. Always displayed with "RFP response kit v1". Not editable per thread or user. Changes ship as v2 with a changelog. |
| Trade-off columns | Win %, Contract value, Expected margin, Pursuit cost, Submission due, Gates |
| Quadrant default axes | x = Win probability, y = Expected margin (user can switch to rubric axes) |
| Plan bindings (G7) | deadline = `submission_due`; milestone = `questions_due`; requirement lists = `mandatory_requirements[]` plus any approved gates; commitment = "Submit the proposal for `<client>`" |
| Selection objective (G6) | maximize Σ Expected margin; constraint keys map to `kit_context.constraints` |
| Interviewer hints | Which missing facts carry the most decision value (win probability basis, margin, pursuit cost, deadline), phrased as single questions |

### K2. `rfp_vendor_selection` kit (buyer side) · P2 · S (config)

| Config element | Content |
|---|---|
| Fields | `vendor`, `proposal_price` (money), `tco` (money, years), `implementation_months`, `references`, `mandatory_requirements_status{}` |
| Metrics | `difference(tco, lowest_tco)` labeled "TCO vs lowest" (computed across options) |
| Starter rubric **proposal** | Functional/technical fit 25 · Total cost of ownership 20 · Implementation risk & timeline 20 · Vendor viability & references 15 · Integration & compliance 10 · Commercial terms 10 |
| Gate **suggestions** | One per stated mandatory requirement (e.g. "Epic integration proven"); proposal completeness |
| Verdict vocabulary | **Select** · **Shortlist** · **Eliminate** |
| Verdict thresholds (**v1**, fixed) | Same rule as K1 with buyer labels: Select needs all gates pass, score ≥ 60, confidence ≥ 55% and a lead ≥ `close_call_margin` 5 over the next option; any gate fail → Eliminate; otherwise Shortlist |
| Trade-off columns | Price/TCO, TCO vs lowest, Implementation months, Gates |
| Plan bindings | deadline = `kit_context.decision_deadline`; requirement lists = unmet or unknown mandatory requirements; commitment = "Award to `<vendor>`" |

### K3. RFP document facts (optional within the MVP) · P2 · M

Uses G2 with `source: "document"`. When an RFP file is attached, the agent fills
fields and proposes gates (minimum qualifications) and criteria (evaluation
criteria), each with page-anchored quotes. Document-sourced evidence is the
legitimate route above the 75 cap (Articles 7, 14). Two existing gaps must be closed:
- Word attachments are cut off at 15,000 characters (`MAX_CONVERSATION_ATTACHMENT_TEXT_CHARS`).
  Chunk and extract per section instead.
- The scoring evidence corpus (`_thread_user_corpus`) ignores attachment text.

**Acceptance:** a 60-page sample RFP yields its due dates with page citations and
≥ 3 proposed gates. A criterion backed by a document quote can reach `high` confidence.

---

## 4. Scoring integrity requirements (cross-cutting acceptance criteria)

These apply to every thread, with or without a kit. They are release gates for
the RFP MVP. Each needs an automated test unless noted.

| ID | Requirement | Acceptance test |
|---|---|---|
| **SI-1** | **All arithmetic is deterministic code.** Scores, rollups, caps, categories, metrics, thresholds, gate effects, selections and schedules are computed in code. Agent prose may cite only numbers found in canonical records, computed metrics, or the user's own text. | A post-processor on agent replies (extending `_remove_unverified_numeric_sentences`, `strategy.py` ~2509) flags any number not traceable to those sources. A test reply containing "≈$428K" with no matching metric fails, and the same reply citing `metrics.expected_value` passes. |
| **SI-2** | **Same facts and assumptions → same result, by reuse** (owner decision 4). The scoring/planning fingerprint covers the option's facts and attributes, the approved rubric (criteria, weights, gates), the objective lens, the kit and version, and the evidence corpus. It deliberately excludes the model and route: an unchanged decision isn't re-scored just because Jaspen changed models, and stored results stay valid even after the model that produced them is retired. Historical decisions are never rewritten automatically; a fresh judgment needs an explicit re-score. An identical fingerprint **returns the stored result without calling the model** (reuse `ai_operations.request_fingerprint` and idempotency). Any change to those inputs is a changed fact or assumption and triggers holistic re-scoring (SI-4). Model calls that do run use temperature 0. | Requesting a re-score of an unchanged option returns the stored scorecard byte-for-byte, makes no provider call, charges no credits, and logs `reused_stored_result`. Changing one attribute produces a new fingerprint, a full re-score, and a new revision. |
| **SI-3** | **Prose-only changes never move scores.** Wording, tone, title renames and field-label edits go through `patch_scorecard` or non-scoring paths and don't change the fingerprint's fact inputs. | Patching the description and renaming the title leaves `jaspen_score`, every dimension score and the recommendation unchanged. |
| **SI-4** | **Changed facts trigger holistic re-scoring.** A changed fact, attribute or assumption re-judges every criterion of that option in place. No single-field nudges and no manual overrides. | Changing `win_probability` re-scores all criteria. The new score equals the recomputed rollup. There is no endpoint that edits a dimension score directly. |
| **SI-5** | **One canonical scorecard record** (the `scorecards` row, keyed by id) is the source for chat cards, the sidebar, the trade-off, the workspace, PDF/PowerPoint/Excel exports, emails, decision records and agent context. Session snapshots become references or a cache, invalidated on write. | After a re-score, the chat card, sidebar, trade-off row, PDF and agent context all show the same score, dimensions, metrics and recommendation (an end-to-end test compares all five). A stale copy cannot render: chat cards resolve by id at render time. |
| **SI-6** | **A re-score may only update the intended option.** Each option has a stable `option_key`. `generate_scorecard` with `rescore_scorecard_id` must include the option being re-scored, and the backend verifies that the target record's `option_key` matches. | **The backend rejects the request (`rescore_target_mismatch`) when `rescore_scorecard_id` belongs to a different option**, and writes nothing. A test replays the observed failure (re-scoring Commerce City with Aurora's id), which must be rejected with Aurora's record unchanged. Renames go through `patch_scorecard`, never a re-score. |
| **SI-7** | **Re-score writes are atomic and revision-checked**, so concurrent edits are never lost and no duplicate records appear. | Two concurrent writes to one card → one succeeds and the other is told to reload. After any re-score the thread has exactly one record per option. |
| **SI-8** | **Portfolio selection under numeric constraints is computed in code** (G6). | With the 7-bid fixture (cap $60M, max 3), the optimizer returns Children's Hospital + DU Residence Hall + Commerce City ($55M, ≈ $1.56M expected margin); runner-up Children's + DU + Tech TI ($50M, ≈ $1.45M). The agent's answer lists the same set and cites the tool. |
| **SI-9** | **Financial metrics** (expected value, pursuit ROI, per-unit values, TCO differences) **are code-calculated, never model-calculated.** | Each metric shown anywhere has a `formula` and `inputs`. Removing an input nulls the metric. The scoring prompt receives metrics as facts and emits no metric fields. |
| **SI-10** | **Every recommendation decomposes** (G5), with fixed, versioned thresholds. | The card and PDF show every trace step, the thresholds with kit version, and each condition's origin. Recomputing from the stored trace inputs and the recorded threshold version reproduces the recommendation exactly. |

---

## 5. Backlog summary (implementation-ready)

| ID | Item | Priority | Size | Depends on |
|---|---|---|---|---|
| SI-6, SI-7 | Re-score target guard; atomic, revision-checked writes | **P0** | S–M | — |
| SI-5 | Canonical scorecard record across all surfaces | **P0** | M | Codex stabilization |
| SI-1 | Agent-reply numeric traceability post-processor | P1 | M | G4 |
| G1 | Decision Kit registry, validator, thread selection | P1 | M | — |
| G2 | Structured option fields and the facts card | P1 | M | G1 |
| G4 | Deterministic metric library | P1 | S | G2 |
| G3 | Gates | P1 | M | G1 |
| G5 | Decomposable recommendation and recorded verdict | P1 | M | G3, G4, SI-5 |
| G7 | Derived execution plans and failure disclosure | P1 | M/L | G5, planner fix |
| G8 | Kit-aware trade-off presentation | P1 | M | G4, G5 |
| K1 | `rfp_bid` kit configuration | P1 | S | G1–G5, G7, G8 |
| G6 | Constraint-based selection | P2 | M | G4, G8 |
| K2 | `rfp_vendor_selection` kit | P2 | S | K1 |
| K3 | RFP document facts | P2 | M | G2, G3 |
| SI-2 | Fingerprint reuse for identical inputs (no model re-run) | **P1** | S–M | SI-5 |

## 6. What stays generic and unchanged

The agent and the four stages; `set_scoring_rubric`; batch scoring; confidence
caps; `_recompute_jaspen_score`; category bands and tiers; Strategic Necessity
locks; the patch-versus-rescore rule; scenario levers; the WBS model and plan
canvas; decision records and custody; and connectors. Kits only configure.

## 7. Owner decisions (recorded 2026-10-04)

| # | Decision | Where applied |
|---|---|---|
| 1 | Verdict thresholds are fixed, visible, versioned kit methodology constants, not editable per session. The human can override the recommendation when recording the decision. | §0, §1.1–1.2, G1, G5, K1, K2, SI-10 |
| 2 | Framework §4.2's phase sequence and 10–18 task range become guidance. Derived work takes precedence. | G7; draft text in Appendix A.2 |
| 3 | MVP plan-generation failure offers **Retry only**. No generic, canned or draft fallback. | G7 |
| 4 | Identical inputs return the stored result. The model is not re-run for an unchanged decision. Changed facts or assumptions trigger holistic re-scoring. | SI-2 (now P1), SI-4 |
| 5 | Conditions, gates, requirements and recorded commitments are valid plan lineage. Draft a narrow amendment to Article 18. | G7, §1.4; draft text in Appendix A.1 |
| 6 | Sync: open conflicts stay open after a policy change unless the user applies the new policy to them. External tasks appear as External / Unlinked items until linked to a decision source and never change scorecards. | `PM_SYNC_SPEC.md` §5.5, §5.6 |

### Follow-up decisions (confirmed 2026-10-04)

| # | Decision | Where applied |
|---|---|---|
| 7 | Each recommendation stays tied to its original kit version. Open decisions are never updated automatically when a new version ships. An explicit "Recompute recommendation under v2" action is offered: code only, no model call, unless the underlying facts or evidence changed (in which case it's a normal holistic re-score). | G5 |
| 8 | Stored results stay valid when the model that produced the judgment is retired. Historical decisions are never rewritten automatically. A fresh judgment requires an explicit re-score. | SI-2 |
| 9 | Article 18 v1.1 and Framework §4.2 v1.1 approved and **applied** to `docs/JASPEN_CONSTITUTION.md` and `docs/JASPEN_DECISION_INTELLIGENCE_FRAMEWORK.md`, each with a changelog entry. | Appendix A (now a record) |
| 10 | Tasks added manually in Jaspen without decision lineage stay in the Unlinked section until the user links them to a valid source. | G7; `PM_SYNC_SPEC.md` S0, §5.6 |

No open constitutional questions remain for this spec.

---

## Appendix A — Amendments (applied 2026-10-04; kept here as the rationale record)

### A.1 Constitution, Article 18 (v1.1, applied)

**Current text**

> **Article 18 — Plans are derived, not invented.**
> Every task in an execution plan traces to the decision that spawned it — a weak
> dimension, a named risk, or a stated recommendation. A plan is the scorecard
> restated as work.
> *Forbids:* generic template plans; tasks with no lineage to the decision.

**Proposed text**

> **Article 18 — Plans are derived, not invented.**
> Every task in an execution plan traces to the decision that spawned it — a weak
> dimension, a named risk, a stated recommendation, a condition attached to the
> recorded decision, a gate that failed or remains unresolved, a requirement
> stated as part of the decision, or a commitment the human recorded. A plan is
> the decision restated as work.
> *Forbids:* generic template plans; tasks with no lineage to the decision;
> lineage the model invents rather than draws from the decision's recorded
> elements.

**Amendment note (for the Constitution's changelog):** *v1.1 — 2026-10-04.
Deliberate amendment. Lineage is extended from scorecard elements to the
recorded decision's own elements (conditions, gates, requirements, commitments),
so a decision that records "Bid, subject to these conditions, by this deadline"
can be executed without templates. Scope is narrow: the enumeration grows, but
the prohibition on generic and template plans is unchanged and gains an explicit
ban on invented lineage. "A plan is the scorecard restated as work" becomes "the
decision restated as work" because the recorded decision now includes the human's
verdict and conditions.*

### A.2 Framework §4.2 — Phase logic and shape (v1.1, applied)

**Current text (first sentence)**

> 10–18 tasks across 4–6 phases following a fixed arc: **Discovery → Planning →
> Build/Execute → Validate → Launch → Operate.**

**Proposed text**

> Plans are sized and phased by the derived work. The arc **Discovery → Planning
> → Build/Execute → Validate → Launch → Operate** and a typical envelope of 10–18
> tasks across 4–6 phases are **guidance** the planner may use when they fit the
> decision. They are not a required structure. Derived work takes precedence:
> every lineage item (§4.1 and Constitution Article 18) must be covered, phases
> are named for the work they group, and no task is added to fill a phase or reach
> a count.

The rest of §4.2 (task taxonomy) is kept, with `lineage` added to the taxonomy
list. Framework Appendix A item 5 ("one plan size") can then be marked resolved,
referencing this change.
