# Decision Impact Report — Measurement Contract and Specification

**Status:** Draft specification. No implementation.
**Branch:** `feature/decision-impact-report`
**Methodology version:** `impact-v1`
**Supersedes:** nothing. Additive to the Decision Record (Art. 20–21).

---

## 0. Purpose

The Decision Impact Report documents **what changed about a decision** between the
moment it was submitted to Jaspen and the moment the analysis closed.

It answers one question, narrowly: *what is different about the structure,
evidence, assumptions, alternatives, trade-offs, risks, execution conditions, and
verification of this decision now, compared with what was submitted?*

It exists because Jaspen's central claim — that a decision leaves the process
better founded than it entered — is currently unevidenced. A buyer has no
artifact to inspect, and neither do we. This spec defines the evidence layer that
makes the claim inspectable.

### 0.1 What this report is not

- **Not a claim about business outcomes.** The report never asserts that the
  decision will go better, that the recommendation is more likely to be correct,
  or that value was created. It documents the state of the decision record. What
  happens in the world afterwards is tracked separately, by outcome capture on
  the Decision Record.
- **Not a quality score.** There is deliberately no composite "decision
  improvement score" (see §1.3).
- **Not a judgment of the user.** Before and After are two **states of a
  decision**, not a bad state and a good state. A thin baseline is a normal
  starting condition, not a deficiency, and the report's language must not imply
  otherwise (§7.3).
- **Not refund or guarantee machinery.** No refund logic, entitlement change,
  billing hook, or public guarantee language is in scope for this branch. The
  evidence layer is built and validated first; commercial framing is a separate,
  later decision informed by real output.

---

## 1. Principles

**1.1 Before and After are states, not grades.**
Every rendered comparison is symmetrical in tone. The report says "the submission
contained 2 alternatives; the closed analysis contains 3" — never "you only
provided 2."

**1.2 Verification counts as impact, on equal footing with addition.**
A user may arrive with a strong recommendation and leave with the same
recommendation. If Jaspen materially improved the evidentiary basis, quantified
exposures that were qualitative, validated assumptions, stress-tested weightings,
or confirmed execution conditions, that is impact. The predicate in §5 has an
independent route to `Material` that requires no new structure at all. This is
not a consolation path — for well-prepared users it is the *primary* path.

**1.3 No synthetic composite score.**
A single number like "decision quality: 74" cannot be independently defended: the
weighting between, say, "one new alternative" and "eleven points of evidence
coverage" would be our invention, and any buyer entitled to scrutinise it would
be right to. The report therefore publishes **transparent deterministic measures
and the underlying evidence**, plus a three-value verdict whose predicate is
fully stated. Readers can recompute the verdict by hand from the report.

**1.4 Code counts; models do not.**
Every number in the report is produced by counting persisted structures. No
measure, count, delta, or verdict may originate from a model. This is the same
discipline `decision_confidence.decision_summary()` already follows, and it is
what allows the report to be quoted in a room.

**1.5 The baseline is captured, not reconstructed.**
A baseline inferred from the transcript after the fact is unverifiable — we could
have tuned it. The baseline is snapshotted at intake, shown to the user, and
sealed (§3).

**1.6 The report must be able to say "nothing material changed."**
A report that can only ever find impact is marketing. `No material change` is a
first-class, reachable verdict with a golden test fixture (AT-31).

---

## 2. Measurement contract

### 2.1 The eight facets and the measures that carry them

| Facet (from product intent) | Carried by |
| --- | --- |
| Structure | `criteria_defined`, `criteria_weighted`, `readiness_categories_addressed` |
| Alternatives | `alternatives_evaluated` |
| Evidence | `evidence_backed_pct`, `criteria_grade_profile` |
| Assumptions | `assumptions_validated`, `assumptions_open_labeled` |
| Trade-offs | `exposures_quantified`, `criteria_weighted` |
| Risks | `risks_documented` |
| Execution conditions | `execution_dependencies` |
| Verification | the whole of Family B |

### 2.2 Family A — Structure measures

What the decision contains.

| ID | Measure | Source of truth | Counting rule |
| --- | --- | --- | --- |
| `A1` | `alternatives_evaluated` | peer scorecard list (`decision_records._collect_peer_scorecards`) | distinct scored options |
| `A2` | `criteria_defined` | `session.scoring_rubric` | distinct rubric criteria |
| `A3` | `criteria_weighted` | `session.scoring_rubric` | criteria carrying an explicit, non-default weight |
| `A4` | `risks_documented` | scorecard `top_risks` | distinct risks; a risk with a mitigation is counted once, and mitigation presence is reported separately, not as a second risk |
| `A5` | `execution_dependencies` | `thread_data.project_wbs` | distinct identified dependencies |
| `A6` | `readiness_categories_addressed` | `intake_readiness._compute_readiness` | categories the deterministic engine marks addressed |

### 2.3 Family B — Verification measures

How well founded the contents are. **This family is the reason a decision can
close with the same recommendation and still show material impact.**

| ID | Measure | Source of truth | Counting rule |
| --- | --- | --- | --- |
| `B1` | `evidence_backed_pct` | `decision_confidence` | weighted % of the decision resting on evidence |
| `B2` | `assumption_dependent_pct` | `decision_confidence` | complement of B1; reported, never independently thresholded |
| `B3` | `criteria_grade_profile` | `decision_confidence` | histogram over `{high, medium, low, assumed}` |
| `B4` | `assumptions_validated` | grade transition | baseline items graded `low`/`assumed` that now grade `medium` or better |
| `B5` | `assumptions_open_labeled` | grade + record | items still unsupported **and** explicitly labeled as such in the record |
| `B6` | `exposures_quantified` | `decision_confidence` swing | criteria carrying a computed numeric swing that had none at baseline |

`B5` deserves a note: leaving an assumption open is not a failure, and the
measure exists because *labeling* an unresolved assumption is itself a verified
improvement over carrying it silently. It counts as impact.

### 2.4 Counting rules that apply to every measure

**Identity.** Items are identified by stable key or id, never by label. Renaming
a criterion is not adding one. This is load-bearing: the sidebar can reword a
criterion (commit `27b62f99`), and a rename must produce zero measured movement.

**Null versus zero.** A measure is `0` when the facet applies and the decision
contains none of it. A measure is `null` when the facet does not apply to this
decision type — for example, `A5 execution_dependencies` on a decision with no
implementation phase. `null` measures are excluded from the predicate entirely,
on both sides, and the report names them under `not_applicable` so their absence
is visible rather than silent. A measure may never be recorded as `0` because a
subsystem failed to run; that condition is `unavailable` and blocks report
generation (AT-24).

**Directionality.** Every measure has a declared direction. All Family A measures
and `B1`, `B4`, `B5`, `B6` increase with impact. `B2` decreases. `B3` moves by
grade band. No measure is ambiguous, and none is allowed to be interpreted in
whichever direction favours a verdict.

**Baseline sources differ from closing sources.** The tables above name the
source of truth at close, when a rubric and scorecards exist. At intake they do
not, so baseline values are obtained under the basis rules in §3.7 instead. The
measure *definitions* are identical on both sides — only the provenance differs.

**Determinism.** Given identical persisted inputs, the measure set is
byte-identical across runs, processes, and machines. No timestamps, ordering, or
model output enter a measure value (AT-20).

---

## 3. The baseline: capture, correction, sealing, immutability

### 3.1 Storage

The baseline lives in its own table, `decision_baselines`, keyed by
`(user_id, thread_id, epoch)`.

It is **not** stored inside `DecisionRecord.record`. Two reasons:

1. **Lifecycle.** The baseline is captured at intake; the Decision Record is
   assembled after analysis. The baseline must be able to exist before any
   record row does.
2. **Immutability.** `decision_records.create_or_refresh_record()` re-derives
   `_DERIVED_FIELDS` and writes `record=payload` wholesale on the create path. A
   baseline living in that payload is one refresh away from being overwritten.
   The codebase already established the correct pattern for this — human-owned
   fields (`final_decision`, `outcomes`, `lessons_learned`) were deliberately
   kept outside `record` "so a re-derivation of the analysis can never clobber
   them." The baseline is subject to the same hazard and gets the same treatment,
   one step further out.

**`assemble_record_payload()` must have no code path that can author a baseline.**
The baseline is written only by `decision_impact.capture_baseline()`. This is a
structural guarantee, not a convention (AT-10).

### 3.1.1 The row holds two payloads: the raw submission and the derived measures

A baseline that preserved only the derived measure set would be a summary of
evidence, not evidence. Anyone auditing the report — a buyer, a reviewer, or us
in six months — could see that we recorded "2 alternatives at intake" but could
not check that claim against anything. The derivation would be unfalsifiable,
which is the precise failure mode §1.5 exists to prevent.

The sealed row therefore holds both halves:

| Field | Contents |
| --- | --- |
| `submission_payload` | the raw, verbatim material the user supplied at intake |
| `measures` | the deterministic measurements derived from it (§2) |

`submission_payload` is stored **verbatim**: no normalization, no summarization,
no model rewriting, no truncation. It contains the user turns as submitted (text,
role, timestamp), attachment references (filename, byte size, content hash, and
storage locator), connector references active at intake, any structured intake
fields, and any content the user added during the correction window. Where the
attachment bytes themselves are not retained under the storage policy, the hash
and locator are retained regardless, so the chain still resolves to a specific
artifact rather than to a description of one.

### 3.2 Capture point

The draft baseline is computed at the **first analyzable submission**: the first
point at which the thread has enough content for `_compute_readiness` to return a
profile. Computing the draft is free — it is the same deterministic engine the
readiness sidebar already runs.

### 3.3 The correction window — "Here's what Jaspen received"

Before analysis begins, the user is shown the draft baseline as a plain
statement of receipt:

> **Here's what Jaspen received**
> 2 options under consideration · 4 stated assumptions · 3 supporting sources ·
> no explicit decision criteria · no quantified downside · no execution
> dependencies identified
>
> *Anything missing? Add it now — this is the starting point Jaspen will compare
> against.*

The user may add or correct anything. Corrections replace the draft in place; the
draft has no evidentiary standing and no history is kept of it.

This window is the anti-gaming property, and it works by cutting against us:
**every correction the user makes shrinks the delta we can later report.** A
baseline the user has been invited to fatten, and has accepted, is one we cannot
be accused of having thinned. It is also, incidentally, good onboarding — it
shows a user what a complete decision brief looks like at the only moment the
information is useful to them.

The window must never block. Consistent with the frictionless-help principle,
analysis proceeds if the user ignores it.

### 3.4 Sealing

The baseline seals on the earlier of: the user confirming it, or analysis
starting. On seal the row records:

- `sealed_at` — UTC timestamp
- `sealed_by` — `user_confirmed` | `auto_on_analysis`
- `submission_hash` — SHA-256 over the canonical JSON serialization of
  `submission_payload`
- `measures_hash` — SHA-256 over the canonical JSON serialization of `measures`
- `content_hash` — SHA-256 over both, in that order
- `readiness_spec_version` and `methodology_version` in force at seal time

Canonical serialization is sorted keys, no whitespace, UTF-8. The two component
hashes exist so that a mismatch identifies *which* half diverged; a single
combined hash would prove only that something did.

### 3.5 Immutability

After sealing, the row is write-once. The service layer raises on any mutation
attempt; no route, task, or admin path offers an edit. The `content_hash` is
recomputed on read and a mismatch renders the report ungenerable rather than
generating a report from a tampered baseline (AT-12).

### 3.6 Epochs

Decisions legitimately change. If the user materially restates the decision —
new options, a different question — we do **not** amend the sealed baseline and
we do not pretend the old one still describes the work.

A new **epoch** opens with its own sealed baseline. The impact report is always
reported per epoch, and a decision with multiple epochs renders them in sequence
rather than collapsing them. What triggers an epoch boundary is deliberately left
open in this draft (§11, Q1) — it is the one rule that needs real transcripts
before it can be written honestly.

### 3.7 The evidence chain

The four links below are the reason this feature exists. Each must be
independently inspectable, and each must resolve to the one before it.

| Link | Held by | Established by |
| --- | --- | --- |
| 1. What the user supplied | `baseline.submission_payload` | verbatim capture at intake, sealed |
| 2. What was measured from it | `baseline.measures` | deterministic derivation over link 1 |
| 3. What Jaspen challenged and validated | `decision_challenge_events` | typed events emitted at the call site (Phase 2) |
| 4. What the decision became | `current.measures` | the same measurement contract at close |

**Link 2 is re-derivable from link 1.** Re-running the measurement engine over
`submission_payload`, at the `readiness_spec_version` and `methodology_version`
recorded on the row, must reproduce `measures` exactly. This is the property that
makes the baseline self-verifying: the derived half can always be checked against
the raw half, by us or by anyone we hand the record to (AT-18).

#### Measure basis — how a baseline measure is allowed to acquire its value

At intake there is no rubric, no scorecard, and no confidence profile: the
analysis has not run. Baseline measures therefore cannot come from the same
sources their closing counterparts come from, and the spec has to say what they
*can* come from. Every baseline measure carries a `basis`:

| Basis | Meaning | Counts in the predicate |
| --- | --- | --- |
| `deterministic` | derived by code from `submission_payload` — e.g. `A6` from `_compute_readiness` | yes |
| `user_confirmed` | proposed in the correction window and confirmed by the user | yes |
| `proposed_unconfirmed` | proposed in the correction window, never confirmed | **no** |

A model **may** propose a draft reading of a prose submission — "this looks like
2 options and 4 stated assumptions" — because extracting structure from free text
is exactly what a model is good at and a keyword rule is not. A model may **never**
author a sealed measure that counts. The user's confirmation is what converts a
proposal into evidence, and §1.4 is preserved: the counting that produces a
verdict is still done by code over confirmed or deterministic inputs.

When a baseline seals `auto_on_analysis`, unconfirmed proposals seal as
`proposed_unconfirmed`. They are stored and displayed, so the chain stays
complete and the reader can see what was proposed, but they are excluded from
movement calculation (§5.2) and reported under `excluded_unconfirmed` (§6). The
effect is that a user who ignores the correction window gets a narrower impact
report rather than a fabricated one — and confirming is the only thing that
widens it. That asymmetry should be visible in the correction UI, and it must not
be turned into a block.

#### Custody

`submission_payload` is raw customer material and is Ring 1 by default under
Art. 21, with the same custody treatment as the Decision Record itself. It is
never included in Ring 2 library derivations, and never enters the Ring 3
evaluation corpus, unless the record's existing consent flags independently allow
it. A Ring 2 export must carry the measures without the raw submission (AT-19).

---

## 4. Event taxonomy — the challenge ledger

Counts alone show that a decision changed. They cannot show that **Jaspen** was
the cause. The ledger is what separates "the record grew" from "the record grew
because the analysis pressed on it."

### 4.1 Storage and invariants

Append-only table `decision_challenge_events`, keyed by
`(user_id, thread_id, epoch, seq)`.

- **Append-only.** No update, no delete, no soft-delete. Superseding information
  is a new event.
- **Emitted at the call site, at the moment it happens.** Never inferred from a
  transcript afterwards, and never produced by a model asked "what did you
  challenge?" An inferred event is an opinion; an emitted one is a receipt.
- **Idempotent.** Each event carries a `dedupe_key`
  (`type` + `target_id` + `derivation_id`). Re-running analysis must not
  duplicate the ledger.
- **Re-derivation preserves history.** A new analysis pass gets a new
  `derivation_id`; prior events persist and remain in the report.

### 4.2 Event record

```
event_id       uuid
thread_id      str
epoch          int
seq            int          monotonic within (thread_id, epoch)
occurred_at    datetime     UTC
type           enum         see 4.3
target_kind    enum         criterion | alternative | assumption | risk | dependency | weighting
target_id      str          stable id, never a label
origin         str          emitting subsystem, e.g. 'readiness', 'scorer', 'sidebar'
user_visible   bool         was this actually surfaced to the user?
derivation_id  str
dedupe_key     str          unique
payload        json         minimal deterministic detail; no prose
```

`user_visible` is not bookkeeping. An event the user never saw did not challenge
anyone, and §5.4 caps the verdict on that basis.

### 4.3 Types

**Challenge events** — Jaspen pressed on something.

| Type | Emitted when |
| --- | --- |
| `evidence_requested` | Jaspen asked for the source behind a criterion or assumption |
| `assumption_flagged` | an input was classified as assumption rather than evidence |
| `weighting_challenged` | Jaspen questioned or proposed a change to a criterion weight |
| `alternative_introduced` | an option absent from the sealed baseline was added |
| `criterion_introduced` | a criterion absent from the sealed baseline was added |
| `dependency_surfaced` | an execution dependency absent from the baseline was identified |
| `risk_surfaced` | a risk absent from the baseline was identified |
| `exposure_quantified` | a qualitative exposure was converted to a number |

**Validation events** — Jaspen confirmed or closed out something.

| Type | Emitted when |
| --- | --- |
| `assumption_validated` | an assumption's grade rose to `medium` or better |
| `assumption_unresolved` | analysis closed with the assumption unsupported and explicitly labeled |
| `criterion_verified` | a criterion's basis was checked against a source or connected system |

**Response events** — what the user did about it.

| Type | Emitted when |
| --- | --- |
| `user_supplied_evidence` | the user answered a request with a source |
| `user_declined` | the user explicitly declined to supply it |
| `user_deferred` | the request went unanswered at close |

Response events carry no verdict weight. They exist so the report can be honest
about who did what, and so a "what's still outstanding" view is possible later.

### 4.4 Emission sites

Several of these already occur in the product and simply are not recorded —
readiness follow-up questions, the sidebar criterion edit path, the batch
scorer's evidence contract. Phase 2 instruments existing call sites before adding
any new behaviour. No event type ships without a real emitter; a type with no
call site is removed from the enum rather than left aspirational (AT-27).

---

## 5. The impact predicate

Deterministic, defined in advance, computed by code, reproducible by hand from
the report.

### 5.1 Named constants (`impact-v1`)

```
MATERIALITY_PP                  = 10   # percentage points, B1
STRONG_PP                       = 20   # percentage points, B1
STRONG_ASSUMPTIONS_VALIDATED    = 3    # B4
MATERIALITY_COUNT               = 1    # any count measure: +1 distinct item
```

These are conventions, not discoveries. They are named, versioned, published in
every report under `impact.thresholds`, and changing one bumps
`methodology_version`. A report generated under `impact-v1` is never re-verdicted
under a later methodology.

### 5.2 When a measure has "moved"

- **Count measures** (`A1`–`A6`, `B4`, `B5`, `B6`): at least `MATERIALITY_COUNT`
  distinct new item, by stable identity.
- **`B1`**: increase of at least `MATERIALITY_PP`.
- **`B3`**: at least one criterion improved by at least one grade band.
- **`B2`**: never thresholded independently — it is B1's complement and would
  double-count.
- `null` measures cannot move.
- Measures whose baseline `basis` is `proposed_unconfirmed` cannot move (§3.7).
  Movement is measured against a baseline the user stood behind, or against
  nothing.

### 5.3 Two routes to Material

**Route 1 — Structural.** At least two Family A measures moved, **and** at least
one of the moved measures is `A1`, `A2`, or `A5`. The qualifier prevents a
verdict resting entirely on peripheral growth: added risks and improved readiness
coverage are real, but a decision whose alternatives, criteria, and dependencies
are all unchanged has not been structurally reshaped.

**Route 2 — Verification.** Either:
- at least one Family B measure moved by a strong margin — `B1` by
  `STRONG_PP`, or `B4` reaching `STRONG_ASSUMPTIONS_VALIDATED`; **or**
- at least two Family B measures moved beyond materiality.

Route 2 requires no new structure whatsoever. This is deliberate and is the point
of §1.2.

### 5.4 Verdicts

| Verdict | Condition |
| --- | --- |
| **Material** | Route 1 or Route 2 is satisfied |
| **Limited** | at least one measure moved, but neither route is satisfied |
| **No material change** | no measure moved |

**The attribution cap.** If the ledger contains zero `user_visible` challenge or
validation events for the epoch, the verdict cannot exceed **Limited**,
regardless of how far the measures moved. Growth with no recorded analytical work
behind it may simply be a user who typed more, and we will not claim it. The cap
must be stated in the report when applied, not applied silently.

### 5.5 What the verdict describes

The verdict describes the decision record. It does not describe the decision's
prospects, the recommendation's correctness, or the value delivered. Report
renderers must carry this scope note (§6, `provenance_note`) exactly as
`decision_report.py` carries its own two limits.

---

## 6. Report schema

Versioned JSON. One assembler, `backend/app/decision_impact.py`, mirroring the
role `decision_report.py` plays for the confidence report: **it returns content,
not layout**, and every renderer — workspace panel, email, PPTX — consumes this
same structure. Shape is the caller's job.

```jsonc
{
  "schema_version": 1,
  "methodology_version": "impact-v1",
  "thread_id": "…",
  "record_id": "…",
  "epoch": 1,
  "generated_at": "2026-09-03T14:22:07Z",

  "baseline": {                        // Before Jaspen
    "sealed_at": "…",
    "sealed_by": "user_confirmed",
    "submission_hash": "sha256:…",
    "measures_hash": "sha256:…",
    "content_hash": "sha256:…",
    "readiness_spec_version": "readiness-v2",
    "measures": {
      "A1": { "value": 2, "basis": "user_confirmed" },
      "A2": { "value": 0, "basis": "user_confirmed" },
      "A6": { "value": 3, "basis": "deterministic" }
    },
    "submission_ref": {                // link 1 of the evidence chain (§3.7)
      "baseline_id": "…",
      "turn_count": 4,
      "attachment_count": 2,
      "retrievable": true              // raw payload is fetchable by an entitled reader
    }
  },

  "activity": {                        // What Jaspen examined, challenged, validated
    "counts_by_type": { "evidence_requested": 3, "assumption_validated": 3, "…": 0 },
    "events": [ /* user_visible events, chronological */ ],
    "suppressed_non_visible": 4
  },

  "current": {                         // After Jaspen
    "measured_at": "…",
    "measures": { "A1": 2, "A2": 5, "…": "…" }
  },

  "impact": {                          // Decision impact
    "verdict": "material",             // material | limited | no_material_change
    "routes_satisfied": ["verification"],
    "moved":          [ { "id": "B1", "from": 38, "to": 71, "delta": 33, "threshold": "STRONG_PP" } ],
    "unmoved":        [ { "id": "A1", "value": 2 } ],
    "not_applicable": [ { "id": "A5", "reason": "no implementation phase in scope" } ],
    "excluded_unconfirmed": [ { "id": "A4", "reason": "baseline value never confirmed" } ],
    "attribution_cap_applied": false,
    "thresholds": { "MATERIALITY_PP": 10, "STRONG_PP": 20, "…": "…" }
  },

  "narrative": {                       // What changed
    "what_changed": "…",
    "generated_by": "model",           // model | template | null
    "grounded_in": { "measures": ["B1","B3","B4"], "events": ["evt_…"] },
    "model_id": "…",
    "generated_at": "…"
  },

  "provenance_note": "This report describes the state of the decision record…"
}
```

The report embeds a reference to the raw submission rather than the submission
itself: the payload can be large, and most readers of the report are not auditing
it. The reference resolves to the sealed material for any reader entitled to it,
which is what link 1 of the evidence chain requires.

`unmoved`, `not_applicable`, and `excluded_unconfirmed` are not padding. A report that lists only what
improved is a highlight reel; listing what did not move is most of what makes the
document credible to a skeptical reader.

---

## 7. Report structure and rendering

### 7.1 Sections, in order

1. **Before Jaspen** — the sealed baseline, stated as receipt.
2. **What Jaspen examined, challenged, and validated** — the ledger, grouped by
   type, user-visible events only.
3. **After Jaspen** — the closing state.
4. **Decision impact** — verdict, the measures that moved, the measures that did
   not, and what was out of scope.
5. **What changed** — the narrative (§8).

### 7.2 Surfaces

Workspace panel, emailed HTML, and PPTX export, via the existing renderer split.
A deck is read from across a room and renders a subset at a different density —
the same rule `decision_report.py` already states. The deck may omit the ledger
detail; it may not omit `unmoved` or the verdict's scope note.

### 7.3 Language rules

- Baseline lines are statements of receipt: "the submission contained…". Never
  "you did not provide", "missing", "gaps", "incomplete", or "weak".
- The word *improved* is permitted only about the decision **record**, never
  about the decision or its likely outcome.
- `No material change` renders plainly, in the same visual weight as the other
  verdicts. It is not softened, buried, or accompanied by consolation copy.

---

## 8. Narrative rules — "What changed"

This is the only section a model writes, and it operates under containment.

**Input.** The model receives *only* the computed measure deltas and the
user-visible ledger events. It does not receive the transcript, the scorecards,
or the recommendation prose.

**Task.** Explain, in continuous prose, the deltas it was given, including the
shift in rationale where the recorded criteria and weightings show one.

**Prohibitions.** It may not introduce any fact, count, cause, risk, or
conclusion absent from its input. It may not characterise the user's original
thinking — the baseline records what was submitted, not what the user believed.
It may not assert that the decision or its outcome improved. It may not restate
the verdict as its own judgment.

**Enforcement.** Every numeral in the narrative must match a value in
`grounded_in`. A narrative failing containment is discarded, not repaired, and
the section falls back to the deterministic template (AT-26).

**Availability.** The model is optional. With no model available the report
renders in full with a templated `what_changed` and `generated_by: "template"`.
The evidence layer never depends on a model being reachable.

---

## 9. Example outputs

### 9.1 Example A — same recommendation, stronger basis

*A vendor consolidation decision. The user arrived with a clear preference for
Option A and left with the same preference.*

**Before Jaspen** — sealed `user_confirmed`
`A1` 2 alternatives · `A2` 5 criteria · `A3` 5 weighted · `A4` 1 risk ·
`A5` 0 dependencies · `B1` 38% evidence-backed ·
`B3` `{high 0, medium 1, low 2, assumed 2}` · `B6` 0 quantified exposures

**What Jaspen examined, challenged, and validated**
3 × `evidence_requested` · 2 × `assumption_flagged` · 1 × `weighting_challenged` ·
2 × `dependency_surfaced` · 4 × `exposure_quantified` ·
3 × `assumption_validated` · 1 × `assumption_unresolved`

**After Jaspen**
`A1` 2 alternatives · `A2` 5 criteria · `A3` 5 weighted · `A4` 3 risks ·
`A5` 2 dependencies · `B1` 71% evidence-backed ·
`B3` `{high 2, medium 2, low 1, assumed 0}` · `B4` 3 validated ·
`B5` 1 open and labeled · `B6` 4 quantified exposures

**Decision impact — Material** (Route 2: verification)
Moved: `B1` +33pp (≥ STRONG_PP) · `B4` 3 (≥ STRONG_ASSUMPTIONS_VALIDATED) ·
`B3` two criteria up one band · `B5` +1 · `B6` +4 · `A4` +2 · `A5` +2
Unmoved: `A1` 2 · `A2` 5 · `A3` 5
Attribution cap: not applied

**What changed**
> The set of options and criteria is unchanged: two alternatives assessed against
> the same five weighted criteria. What changed is the basis. At submission, 38%
> of the weighted decision rested on evidence; it now rests at 71%. Three
> assumptions that carried the decision at intake are now evidence-backed, one
> remains unresolved and is labeled as such, and four exposures that were
> qualitative now carry figures. Two execution dependencies were identified
> during analysis that were not in the submission. The recommendation is the same
> option; the conditions under which it holds are now explicit.

This is the case the report exists for. Nothing structural moved. The verdict is
`Material` on verification alone, and no consolation framing is used to get there.

### 9.2 Example B — structural reshaping

**Before** `A1` 2 · `A2` 0 · `A5` 0 · `B1` 44%
**After** `A1` 3 · `A2` 6 · `A5` 3 · `B1` 52%
**Impact — Material** (Route 1: `A1`, `A2`, `A5` moved; `A2` qualifies).
`B1` moved +8pp — below `MATERIALITY_PP`, so it is reported under `unmoved`
despite pointing the right way. The report says so rather than rounding it into
the win.

### 9.3 Example C — no material change

*A well-prepared operator arrived with a complete brief.*

**Before** `A1` 3 · `A2` 6 · `A3` 6 · `A4` 5 · `A5` 3 · `B1` 74% · `B6` 5
**After** `A1` 3 · `A2` 6 · `A3` 6 · `A4` 5 · `A5` 3 · `B1` 77% · `B6` 5
**Impact — No material change.** `B1` moved +3pp, below `MATERIALITY_PP`. No
count measure moved. Nothing else is claimed.

**What changed**
> The decision closed in substantially the state it was submitted. Evidence
> coverage moved from 74% to 77%, below the 10-point threshold this report treats
> as material. No alternatives, criteria, risks, or execution dependencies were
> added, and no assumption changed grade. Jaspen confirmed the existing analysis
> rather than altering it.

The report states this without apology and without inventing impact. Section 1.6
exists so that this output is a correct result, not a bug.

---

## 10. Acceptance tests

### Baseline integrity

- **AT-10** `assemble_record_payload()` contains no code path that writes a
  baseline; only `capture_baseline()` does. Enforced by test, not review.
- **AT-11** `create_or_refresh_record()` called twice leaves `content_hash`
  identical and every baseline measure unchanged.
- **AT-12** A baseline row whose stored measures no longer match `content_hash`
  makes report generation raise; no report is produced from a tampered baseline.
- **AT-13** Any mutation of a sealed baseline raises at the service layer.
- **AT-14** Corrections before seal are accepted and change the draft.
- **AT-15** Corrections after seal are rejected.
- **AT-16** Seal records `sealed_by: user_confirmed` on confirmation and
  `auto_on_analysis` when analysis starts unconfirmed.
- **AT-17** A baseline can be captured for a thread with no `DecisionRecord` row,
  and links correctly when the record is later created.
- **AT-18** *Evidence chain:* re-running the measurement engine over a sealed
  `submission_payload`, at the versions recorded on the row, reproduces
  `measures` exactly for every `deterministic` measure. A divergence fails the
  build — it means the engine changed without a methodology bump.
- **AT-18b** `submission_payload` round-trips verbatim: what is read back is
  byte-identical to what was submitted, with no normalization, reordering, or
  truncation applied on either write or read.
- **AT-18c** An attachment whose bytes are not retained still resolves to a hash
  and locator on the sealed row.
- **AT-19** *Custody:* a Ring 2 export carries `measures` and omits
  `submission_payload`.

### Measurement

- **AT-20** Two runs over identical persisted inputs produce byte-identical
  measure sets.
- **AT-21** No module in the measure path imports or invokes a model client.
- **AT-22** Renaming a criterion produces zero measured movement (identity by key).
- **AT-23** A facet that does not apply records `null`, is excluded from the
  predicate, and appears under `not_applicable`.
- **AT-24** A measure whose subsystem failed records `unavailable` and blocks
  report generation; it is never silently recorded as `0`.
- **AT-25** `B2` never independently satisfies a movement test.
- **AT-25b** Every baseline measure carries a `basis`; a measure without one is
  a write error, not a default.
- **AT-25c** No model client is reachable from the *sealing* path. A model may be
  invoked only to produce a draft proposal before sealing, and a
  `proposed_unconfirmed` measure never reaches the predicate.

### Narrative containment

- **AT-26** A narrative containing a numeral absent from `grounded_in` is
  discarded and the template fallback is used.
- **AT-26b** With no model available, the report renders in full with
  `generated_by: "template"`.

### Ledger

- **AT-27** Every value in the event-type enum has at least one real emitting
  call site.
- **AT-28** Re-running analysis produces no duplicate events (`dedupe_key`).
- **AT-29** No code path updates or deletes an event row.
- **AT-30** `seq` is monotonic within `(thread_id, epoch)`.

### Predicate

- **AT-31** *Golden fixture:* a well-prepared intake with minor movement returns
  `no_material_change`. This test is the guard on §1.6 and may not be weakened.
- **AT-32** *Golden fixture:* Example A returns `material` via Route 2 with zero
  Family A structural qualifiers moved.
- **AT-33** Route 1 is not satisfied when only `A4` and `A6` moved.
- **AT-34** Boundary: `B1` +9pp does not move; +10pp moves at materiality;
  +19pp does not reach strong; +20pp does.
- **AT-35** Zero `user_visible` events caps the verdict at `limited` even when
  both routes would otherwise be satisfied, and sets
  `attribution_cap_applied: true`.
- **AT-36** All three verdicts are reachable from fixtures.
- **AT-37** The verdict is recomputable by hand from the values published in
  `impact.thresholds`, `impact.moved`, and `impact.unmoved` alone.
- **AT-38** A measure whose baseline `basis` is `proposed_unconfirmed` cannot
  appear in `impact.moved`, and appears in `excluded_unconfirmed` instead.

### Scope

- **AT-40** No module on this branch references refunds, entitlements, billing,
  or guarantee language.

---

## 11. Open questions

- **Q1 — Epoch boundaries (§3.6).** What restatement of a decision is large
  enough to open a new epoch? Needs real transcripts; guessing now would produce
  a rule that either never fires or fires constantly.
- **Q2 — Threshold calibration.** `MATERIALITY_PP = 10` and
  `STRONG_ASSUMPTIONS_VALIDATED = 3` are reasoned starting values, not measured
  ones. They should be reviewed against the first cohort of real reports before
  any external language depends on them.
- **AT-31 as the honest check.** If real usage produces `no_material_change`
  almost never, that is more likely a predicate that is too easy to satisfy than
  a product that always works. Worth watching from the first week.

---

## 12. Build phases

**Phase 1 — deterministic skeleton.** `decision_impact.py` assembler,
`decision_baselines` table, capture and correction UI, measures from the two
existing engines, verdict, workspace panel. No ledger, no model, no new analysis
behaviour. This alone produces a real, defensible artifact.

**Phase 2 — the challenge ledger.** `decision_challenge_events` table; instrument
existing call sites first. This is where the report stops being a diff and starts
being evidence of analytical work — and where the attribution cap in §5.4 stops
binding.

**Phase 3 — narrative and surfaces.** Contained model narrative with template
fallback, plus email and PPTX renderers through the existing split.

**Out of scope, all phases:** refund mechanics, entitlement changes, public
guarantee language. The evidence layer is validated against real decisions first.

---

## 13. Migration note

Two new tables. The Alembic history currently has multiple heads and local dev
provisions via `create_all` (see `docs/DEVELOPMENT.md`), so the head situation
needs resolving before these migrations are authored, or they will land on an
ambiguous base.
