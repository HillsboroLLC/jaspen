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
| `B4` | `assumptions_validated` | challenge ledger | distinct criteria carrying an `assumption_resolved` event |
| `B5` | `assumptions_open_labeled` | challenge ledger | distinct criteria carrying an `assumption_left_open` event |
| `B6` | `exposures_quantified` | challenge ledger | distinct criteria carrying an `exposure_quantified` event |

`B4`, `B5` and `B6` are **ledger measures**. They were unmeasurable in Phase 1
for a specific reason: a free-text assumption at intake and a rubric criterion
at close share no identity, so no honest diff could connect them. The ledger
supplies that identity by keying every event to a stable criterion key, and the
measures become counts of *distinct criteria carrying a recorded event* — no
cross-boundary matching, nothing inferred from prose.

Their baseline value is a deterministic `0`, and not by convention: before
Jaspen ran, Jaspen had resolved nothing, labelled nothing and quantified
nothing. Counting distinct criteria rather than rows is what stops a re-score
that re-states a finding from reading as more work.

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

### 2.5 Two classes of measure

| Class | Meaning | Reported as |
| --- | --- | --- |
| **state** | a property the decision genuinely has, at intake and at close | a Before/After movement |
| **intervention** | something Jaspen did, or caused to become explicit, during the analysis | a count of work done |

`A1`–`A6`, `B1`, `B2` and `B3` are state. `B4`, `B5` and `B6` are
interventions.

**An intervention has no Before, and must not be given one.** "Before Jaspen,
Jaspen had resolved zero assumptions" is definitionally true and says nothing
whatever about the decision the user brought. Rendering it as a `0 → 3` delta
would dress a tautology as a measured improvement — and it would be the most
flattering number on the page, which is exactly why the temptation has to be
closed off in the contract rather than left to a renderer's judgment.

So interventions are **absent from the baseline entirely** — not stored as
zero — and they never enter `moved`, `unmoved` or `not_applicable`. They are
published under `impact.interventions` and rendered in "What Jaspen examined,
challenged, and validated", which is the section that is actually about what
Jaspen did.

They remain deterministic inputs to the predicate (§5.3). They are not demoted;
they are correctly classified.
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

### 3.8 Capture provenance — was the seal in time?

`sealed_by` records **who** sealed. It cannot record **whether the seal was in
time**, and those are different questions with different consequences. A
baseline sealed `auto_on_analysis` at the correct moment is trustworthy; one
sealed `auto_on_analysis` an hour later is not, and both carry the same
`sealed_by`. Every baseline therefore also carries `capture`:

| `capture` | Meaning |
| --- | --- |
| `contemporaneous` | sealed **before** the first analysis mutation |
| `reconstructed` | assembled **after** analysis had already begun |

**Why this is not a formality.** When no baseline was captured in time, the
seal reads the submission from the thread *as it now stands* — which by then
contains every turn the user made during and after the analysis. The "before"
literally includes the after. Comparing the two would produce a tidy,
confident, entirely fictional delta, and it would look exactly like a real one.

Three things reach `reconstructed`: a thread analyzed before this feature
existed, a thread whose analysis-start hook failed, and a thread that never had
a baseline taken. Two reasons distinguish what we know:

| `capture_reason` | Meaning |
| --- | --- |
| `no_baseline_before_analysis` | nothing was captured in time; the payload is post-analysis content |
| `draft_captured_before_analysis_sealed_late` | a draft **was** captured before analysis — and the correction window refuses writes once analysis starts, so its content is provably pre-analysis — but the seal arrived late |

The second is materially better evidence than the first and is recorded
separately for that reason. It is nonetheless treated identically today: not
contemporaneous, no verified comparison. It is the strongest candidate for a
future verified-reconstruction path (§11 Q3), and until that path is defined
and tested, the conservative reading stands.

**Capture is decided by the thread, never asserted by a caller.** It is
computed at seal time from whether the thread has produced scored output.
`seal_baseline()` takes no `capture` argument, and there is no override.

**A failed capture is never laundered by a later seal.** The lazy seal in the
report route exists so that pre-feature threads still get a record, and it
always produces `reconstructed`. Analysis itself must never be blocked by a
baseline failure — a decision the user is waiting on matters more than a row —
so the honest outcome of a failed capture is a report that says the comparison
cannot be made, not an analysis that did not run.
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
id             uuid
user_id        str
thread_id      str
epoch          int
seq            int          monotonic within (user, thread, epoch)
occurred_at    datetime     UTC — authoritative; seq is for rendering
type           enum         see 4.3
target_kind    enum         criterion | dependency
target_id      str          stable key, never a label
target_label   str          for rendering only
trigger        json         the deterministic state the event was derived from
origin         str          emitting subsystem: 'scoring' | 'execution_plan'
actor          enum         jaspen | user_confirmed | user_supplied
user_visible   bool         could the user observe this intervention?
derivation_id  str          the artifact whose write produced it
dedupe_key     str          unique per (user, thread, epoch)
```

Together these answer the six questions a ledger row has to answer: what
happened (`type`), when (`occurred_at`), which decision element (`target_kind`
+ `target_id`), what state triggered it (`trigger`), whose work it was
(`actor`), and whether anyone could see it (`user_visible`).

`trigger` is what makes a row checkable rather than asserted — it carries the
grade, the previous grade, the computed swing. `target_id` is a stable key
rather than a label so a criterion challenged in one pass and resolved three
passes later is recognisably the same criterion (§4.4).

`user_visible` is not bookkeeping. An event the user never saw did not challenge
anyone, and §5.4 caps the verdict on that basis.

### 4.3 Types

Five, each with a real emitter. The draft taxonomy had fourteen; what survived
contact with the call sites is below, and §4.5 says what did not and why.

**Challenge events** — Jaspen pressed on something.

| Type | Emitted when | Emitted from |
| --- | --- | --- |
| `evidence_requested` | a criterion was scored unevidenced (`low`/`assumed`) **and** a specific resolution ask was recorded against it | `upsert_scorecard`, analysis pass |
| `assumption_left_open` | a criterion Jaspen already challenged was re-scored in a **new** pass, is still unevidenced, and Jaspen said so again | `upsert_scorecard`, analysis pass |
| `exposure_quantified` | a criterion's uncertainty was converted into score points, at or above `MATERIAL_SWING_POINTS` | `upsert_scorecard`, analysis pass |
| `dependency_surfaced` | an AI-generated execution plan declared a task dependency | plan generation only |

**Validation events** — Jaspen confirmed something.

| Type | Emitted when | Emitted from |
| --- | --- | --- |
| `assumption_resolved` | a criterion that previously graded `low`/`assumed` now grades `medium` or better | `upsert_scorecard`, analysis pass |

`assumption_left_open` carries the spec's hardest requirement: it must mean
Jaspen **made an unresolved uncertainty explicit**, not that a field stayed
blank. Three conditions enforce that. The criterion must already carry an
`evidence_requested` event — a criterion nobody ever challenged cannot reach
this state however empty it is. A resolution ask must be present on this pass
too, so Jaspen is saying it again rather than merely failing to. And the pass
must be a genuinely new one (§4.4).

### 4.4 Emission sites, and what is deliberately not one

**`upsert_scorecard` is the single scoring chokepoint.** Ten call sites reach
it; it is the only place holding both the previously persisted dimensions and
the ones about to replace them, which is what makes a grade transition
observable at all. Four of the five types come from there.

**`analysis_pass` gates it, and defaults to `False`.** Only three of those ten
call sites are analysis: `/analyze`, `/score-batch`, and the agent's
`generate_scorecard` (which `/score-next` reuses). Renames, in-place prose
edits, display overrides, legacy backfills and tombstones all reach the same
function and none of them is analytical work. A default of `True` would have
turned every backfill into evidence of thinking. A caller that forgets the flag
under-reports, which is the safe direction.

**A retry is not a new pass.** Each scoring run carries an `evaluation_id`; a
replay of one carries the id already persisted. `assumption_left_open` requires
the two to differ, because without that check re-executing an identical request
would record "Jaspen re-examined this and it is still unsupported" when Jaspen
did nothing of the kind. When either id is missing the answer is "cannot tell",
and the event is skipped.

**Plan dependencies come only from generation.** Seven call sites store a plan;
two generate one. The five editing paths do not call the recorder, because a
dependency the user typed into their own plan is theirs.

**Nothing is inferred from prose.** No emitter reads a transcript, and none
calls a model. A model may author the *wording* of a challenge — the product
already has it write the "what would resolve this" line — but the event records
the deterministic state (`grade`, `previous_grade`, `swing_points`) and the fact
that an ask exists. The wording itself is never persisted as a ledger fact.

### 4.5 The types that have no emitter, and why

Three types from the original draft are **absent from the enum**, not merely
unimplemented:

| Type | Why there is no honest emitter |
| --- | --- |
| `criterion_added` | `set_scoring_rubric` carries no authorship provenance, and its documented purpose is storing *the user's own* criteria. Attributing them to Jaspen would claim the user's thinking. |
| `alternative_introduced` | Same problem. Nothing in the scoring tools records whether an option was the user's idea or Jaspen's, and a set difference against the baseline cannot tell "Jaspen proposed Denver" from "the user asked to add Denver". |
| `weighting_challenged` | The product instructs the agent never to invent or alter a user's weights. There is no behaviour to record. |

Adding any of them honestly would need a provenance field on the tool contract
— a product change, and one where the model would be self-reporting its own
authorship, which is close to the line §4.1 draws. It is deliberately not done
here.

Four further draft types (`assumption_flagged`, `risk_surfaced`,
`criterion_verified`, and the three response events) collapsed into the five
above or had no distinct call site. `assumption_flagged` is not separable from
`evidence_requested`: the same state transition produces both.

---

### 4.6 Attribution is measured in distinct interventions, not rows

Every count that can affect the attribution cap or a Material route is a count
of distinct `(type, target_id)` pairs among user-visible, cap-qualifying
events. Never a row count.

The alternative rewards repetition. A decision re-scored six times, with the
same criterion unresolved throughout, did not receive six challenges: it
received one, restated. Counting rows would let ordinary, legitimate
re-evaluation inflate both the cap and the routes without any additional
thinking having happened — and the decisions most likely to be re-run are the
ones going worst.

The pair, rather than the target alone, is the right unit. Asking for evidence
on a criterion, quantifying its exposure, and later resolving it are three
genuinely different contributions to the same criterion; collapsing them would
under-report real work.

Today the dedupe keys already permit only one row per `(type, target)`, so the
two counts coincide. The distinct-pair rule is stated and enforced separately
anyway, because that coincidence is a property of the current keys and not
something a future event type should be free to break.
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
- a **strong** verification signal: `B1` moved by `STRONG_PP`, or `B4` reached
  `STRONG_ASSUMPTIONS_VALIDATED`; **or**
- at least **two** verification signals, of which at least one is a state
  measure that moved.

A signal is a Family B state measure that moved, or a qualifying intervention.

Route 2 requires no new structure whatsoever — three assumptions validated
carries it alone, with every structural count unchanged. That is the point of
§1.2.

**Why the multi-signal branch requires a state measure.** Without that clause a
single stuck criterion satisfies Route 2 by itself: one uncertainty labelled
plus its own exposure quantified is two signals about the same unresolved
thing. Calling that a material change to the decision would be the breadth
version of the repetition inflation §4.6 rules out, and it would fire on
exactly the decisions where Jaspen achieved least.

**Interventions cannot be inflated by re-running an analysis.** Every
intervention count is a count of distinct decision elements, derived from
distinct `(type, target)` pairs in the ledger (§4.6). Six evaluation passes
with one criterion unresolved throughout produce the same count as one.

### 5.4 Verdicts

| Verdict | Condition |
| --- | --- |
| **Material** | Route 1 or Route 2 is satisfied |
| **Limited** | at least one measure moved, but neither route is satisfied |
| **No material change** | no measure moved |

**The attribution cap.** If the ledger contains zero `user_visible`
cap-qualifying events for the epoch, the verdict cannot exceed **Limited**,
regardless of how far the measures moved. Growth with no recorded analytical
work behind it may simply be a user who typed more, and we will not claim it.
The cap must be stated in the report when applied, not applied silently.

With the ledger in place the cap lifts on its own for a thread where Jaspen
genuinely challenged something, and keeps binding for one where it did not —
which is the behaviour Phase 1 could only approximate by binding always. Two
filters decide it: `user_visible`, because an intervention nobody could observe
did not challenge anyone; and `CAP_QUALIFYING_TYPES`, declared separately from
the taxonomy so that a future bookkeeping event can enter the ledger without
entering this count.

### 5.5 What the verdict describes

The verdict describes the decision record. It does not describe the decision's
prospects, the recommendation's correctness, or the value delivered. Report
renderers must carry this scope note (§6, `provenance_note`) exactly as
`decision_report.py` carries its own two limits.

### 5.6 The fourth state: `unverified_baseline`

A `reconstructed` baseline (§3.8) stops before the predicate runs entirely.

| Verdict | Condition |
| --- | --- |
| **Unverified baseline** | `capture` is not `contemporaneous` |

This is **not a fourth degree** of change. `No material change` says a
comparison was made and found little; `unverified_baseline` says no comparison
could be made. Conflating them would be the more damaging error, because one is
a finding and the other is an absence.

It is terminal. No quantity of measured movement promotes it, the attribution
cap does not apply to it (there is nothing to cap), and `routes_satisfied` is
empty rather than reporting routes that "would have" fired.

**No movements are published for it at all** — `moved`, `unmoved`,
`not_applicable` and `excluded_unconfirmed` are all empty. A caveated figure is
still a figure: a reader, a later renderer, or an export can lift it out of its
caveat, and the number would be fictional. The state at reconstruction is still
published under `current` and under a qualified heading; what is withheld is
the comparison, because there is nothing honest to compare.

**`verified_comparison`** is the boolean that carries this. It is a fact about
the evidence — "was this compared against a baseline captured in time" — not a
commercial term, and it is deliberately phrased that way so a later eligibility
question can key off it without this branch containing any eligibility logic.
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
    "sealed_by": "user_confirmed",       // who sealed
    "capture": "contemporaneous",        // whether the seal was in time (§3.8)
    "capture_reason": null,
    "verified_comparison": true,
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
    "verdict": "material",             // material | limited | no_material_change | unverified_baseline
    "verified_comparison": true,       // false ⇒ every list below is empty (§5.6)
    "capture": "contemporaneous",
    "capture_reason": null,
    "withheld_reason": null,           // set when the comparison was not made
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
    "generated_by": "template",        // deterministic report narrative
    "grounded_in": { "measures": ["B1","B3","B4"], "events": ["evt_…"] },
    "model_id": "…",
    "generated_at": "…"
  },

  "provenance_note": "This report describes the state of the decision record…",
  "reconstruction_note": null          // set when capture is not contemporaneous
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

### 7.4 Rendering a reconstructed baseline

A reconstructed baseline may be shown. It may never be labelled as a before
state.

- The **Before Jaspen** heading is replaced, not annotated. A qualifier beneath
  a heading that already made the claim does not undo the claim.
- The reconstruction note renders **above** every section it qualifies, not as
  a footnote below them.
- Thresholds are not printed. They exist so a reader can recompute the verdict,
  and printing them where no verdict was reached implies one was applied.
- `Baseline unavailable for verified impact comparison` renders at the same
  visual weight as the other verdicts.

---

## 8. Narrative rules — "What changed"

This section is assembled deterministically from the same computed measures and
user-visible ledger counts returned elsewhere in the report. Opening or
refreshing a report does not invoke a model.

**Input.** The template receives *only* the computed measure deltas, the
user-visible ledger counts, and the already-computed leading option. It does not
receive the transcript, scorecards, or recommendation prose.

**Task.** Tell the before/challenge/after story in continuous prose without
creating a causal relationship the ledger does not record.

**Prohibitions.** It may not introduce any fact, count, cause, risk, or
conclusion absent from its input. It may not characterise the user's original
thinking — the baseline records what was submitted, not what the user believed.
It may not assert that the decision or its outcome improved. It may not restate
the verdict as its own judgment.

**Enforcement**, mechanical and in three parts:

1. Every numeral in the paragraph must appear in the input it was given.
2. A published list of claims the report may never make — outcome claims
   (`better decision`, `more likely to succeed`), guarantee language, and
   first-person judgment — is checked for outright.
3. **Causal and relational language is banned outright.** This is the subtler
   failure the numeral check cannot catch: every fact can be legitimate while
   the *relationship* asserted between two of them is invented.

   The ledger has no relational provenance. It records that Jaspen asked for a
   source on `cost`, and separately that `cost` later graded `high`. It does
   not record that the first caused the second — and in many threads it did
   not: the user may have supplied the figure for their own reasons, or a
   re-score may have moved it. A narrative asserting the link would be
   inventing the single most valuable claim in the report.

   Banned: `because`, `therefore`, `which led to`, `resulting in`, `caused`,
   `revealed`, `improved`, `strengthened`, and their close relatives, matched
   on word boundaries. `improved` and `strengthened` are here rather than
   under (2) because their problem is relational rather than evaluative:
   "coverage improved" smuggles in a judgment about cause where "coverage moved
   from 38 to 71" states what happened.

   Preferred instead: `also`, `during the analysis`, `the report recorded`, and
   separate factual sentences. The prompt says so explicitly — banning without
   offering an alternative produces refusals rather than better prose.

   The ban is **unconditional today**. It becomes conditional only if the
   ledger ever carries explicit relational provenance, and not before.

The narrative may never claim an intervention changed the recommendation, the
confidence, the readiness, an outcome, or any other measure.

**The deterministic template is held to the same rules** (AT-77d). A fallback
that quietly used causal phrasing would make the constraint cosmetic, since the
template is what most reports render.

A narrative is assembled only after the impact and activity blocks are final.
It cannot alter a measure, movement, intervention count, or verdict. The same
`activity_counts` object is returned to the UI and passed to the narrative, so
the story cannot say that no analytical work occurred while the audit trail
lists recorded challenges.

**An unverified baseline gets no comparative narrative.** There is no
comparison to explain, and prose about one would be the same fiction §5.6
refuses to publish in numbers (AT-74).

**Availability and cost.** The report renders in full with
`generated_by: "template"`. The evidence layer never depends on a model being
reachable, and reading the report never creates model usage.

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

### The challenge ledger

- **AT-61** `assumption_left_open` is reachable only for a criterion Jaspen
  already challenged, in a new pass, where Jaspen flagged it again. A blank
  field never reaches it.
- **AT-62** `analysis_pass` defaults to `False`, and a plain
  `upsert_scorecard` call writes no events.
- **AT-62b** Exactly the three analysis call sites set it; backfill and
  tombstone paths never do.
- **AT-63** Only the two plan-generation paths record dependencies; the five
  plan-editing paths do not.
- **AT-64** The cap counts only `user_visible` events of cap-qualifying types.
- **AT-64b** `CAP_QUALIFYING_TYPES` is declared separately from `EVENT_TYPES`.
- **AT-65** A challenge and its later resolution resolve to the same
  `target_id`, so the report can connect them rather than counting them twice.
- **AT-66** No emitter reaches a model client, and no event persists model
  prose — only the state and the fact an ask exists.
- **AT-67** `B4` and `B5` are measurable from the ledger with no inference, and
  their baseline is a deterministic zero.
- **AT-68** Recorded, observable analytical work lifts the attribution cap.
- **AT-69** With nothing recorded, the cap still binds.
- **AT-70** The report lists only observable events and counts the rest under
  `suppressed_non_visible`.

### Measure classes and attribution

- **AT-71** Six legitimate evaluation passes with one criterion unresolved
  throughout produce one challenge, not six.
- **AT-71b** Attribution counts distinct `(type, target)` pairs, so a
  duplicate row that slipped past the dedupe key still counts once.
- **AT-72** More passes cannot promote a verdict.
- **AT-73** An intervention never appears in `moved`, `unmoved` or
  `not_applicable`.
- **AT-67b** Interventions are absent from the baseline, not stored as zero.

### The narrative

- **AT-77** Causal constructions fail containment even when every figure in
  them is legitimate.
- **AT-77b** The same facts in additive construction pass.
- **AT-77c** Word-boundary matching prevents false positives.
- **AT-77d** The deterministic template satisfies containment for every
  verdict.
- **AT-77e** The prompt names the banned terms and the preferred alternatives.
- **AT-77f** An option name containing a digit does not break the template.
- **AT-74** An unverified baseline produces no comparative narrative, and the
  model is not called at all.
- **AT-75** The measure path remains model-free.
- **AT-76** The narrative cannot alter a measure or a verdict.

### Capture provenance

- **AT-50** A baseline sealed before analysis records `contemporaneous` and no
  reason.
- **AT-51** A thread analyzed with no prior capture records `reconstructed` /
  `no_baseline_before_analysis`.
- **AT-52** A draft captured before analysis but sealed after records
  `reconstructed` / `draft_captured_before_analysis_sealed_late`, and is still
  not contemporaneous.
- **AT-53** *The load-bearing one:* a failed analysis-start hook followed by a
  later lazy seal produces a `reconstructed` baseline. The failure cannot be
  laundered by the seal that follows it.
- **AT-54** `seal_baseline()` accepts no `capture` argument, and a caller
  asserting `user_confirmed` on an already-analyzed thread still gets
  `reconstructed`.
- **AT-55** A reconstructed baseline returns `unverified_baseline` with
  `verified_comparison: false` and empty `routes_satisfied`, no matter how far
  the measures moved.
- **AT-56** A reconstructed baseline publishes no movements at all: `moved`,
  `unmoved`, `not_applicable` and `excluded_unconfirmed` are empty.
- **AT-57** `verified_comparison` is `true` only for a contemporaneous
  baseline, for every reconstruction reason.
- **AT-58** The report carries `reconstruction_note` and never presents a
  reconstructed baseline as what Jaspen received.
- **AT-59** The withheld narrative states the reason and contains no figures.
- **AT-60** Scored output in the `scorecards` table closes the correction
  window. (Detecting it requires the peer collector's `user_id`/`thread_id`;
  without them it falls back to the legacy session stores and answers `False`
  for a fully analyzed thread.)

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
- **Q3 — A verified-reconstruction path.** For genuinely pre-feature threads,
  immutable message history *might* allow a deterministic reconstruction of
  exactly what existed before the first scoring event, which would turn some
  `reconstructed` baselines into verified ones. That capability is **not
  assumed to exist**. Nothing may depend on it until it is defined, built and
  tested on its own terms. `draft_captured_before_analysis_sealed_late` is the
  case most likely to be rescued by it.
- **AT-31 as the honest check.** If real usage produces `no_material_change`
  almost never, that is more likely a predicate that is too easy to satisfy than
  a product that always works. Worth watching from the first week.

---

## 12. Build phases

**Phase 1 — deterministic skeleton.** `decision_impact.py` assembler,
`decision_baselines` table, capture and correction UI, measures from the two
existing engines, verdict, workspace panel, and the seal at analysis start. No
ledger, no model, no new analysis behaviour. This alone produces a real,
defensible artifact.

The seal is wired at four entry points, each a single call to
`seal_baseline_on_analysis_start`: the `/analyze`, `/score-next` and
`/score-batch` strategy routes, and `_execute_mutation_tool` in the agent —
the one chokepoint the whole conversational path funnels through on its way to
scoring. The call is idempotent, so the entry points need no knowledge of one
another, and best-effort, so it can cost a report but never an analysis. The
correction window's own guard (no writes once a thread has scored output) holds
the content boundary regardless of whether the hook runs.

**Phase 2 — the challenge ledger.** *Done.* `decision_challenge_events`, five
event types, instrumented at existing call sites only. This is where the report
stops being a diff and starts being evidence of analytical work, where `B4`/`B5`
become measurable, and where the attribution cap stops binding for threads that
earned it.

**Phase 3 — narrative.** *Done for the workspace.* The published narrative is
deterministic and assembled from the final impact block and the exact ledger
counts returned to the UI. The earlier contained-model experiment remains
isolated in `decision_narrative.py` for tests and reference, but report assembly
does not call it; opening a report cannot spend model credits or produce a
different account of the same record.

**Phase 3b — other surfaces.** Email and PPTX, through the existing renderer
split. Deliberately not built yet: the workspace report is the product, and the
customer-facing hierarchy should be judged in context before it is duplicated
into two more renderers that would then have to be changed in three places.

**Out of scope, all phases:** refund mechanics, entitlement changes, public
guarantee language. The evidence layer is validated against real decisions first.

---

## 12b. Seeing it work

`backend/scripts/seed_impact_demo.py` builds three demo decisions in a local
dev database and prints the verdict each produces. Same SQLite-only guard as
`init_dev_db.py`; it never runs against a remote database, and it owns and
rebuilds only its own three threads.

| Thread | Shape | Verdict |
| --- | --- | --- |
| `impact-demo-thin` | one option, two criteria, nothing quantified | `material`, both routes |
| `impact-demo-strong` | three options, five weighted criteria, leader unchanged | `material`, verification route only |
| `impact-demo-quiet` | fully evidenced brief, one clean pass | `no_material_change` |

The third is the one to check first. It is the case the methodology has to be
able to report honestly, and it is what would quietly disappear if the demo
data were written to flatter the product.

---

## 13. Migration note

Two new tables across the phases: `decision_baselines` (Phase 1) and
`decision_challenge_events` (Phase 2).

The Alembic history was checked before authoring: it resolves to a **single
head**. The branch points in its past (`e4b2c1d9f7a3`, `f6e7d4c9b21a`,
`b2f9a2d4c1ef`) were all merged, so there is no ambiguous base — an earlier
draft of this note said otherwise and was out of date.

`decision_baselines` is migration `c1a7f3d95b04`, on `b7e2d91a4c03`. Capture
provenance (§3.8) follows in `d2b8e64af117`. Upgrade and downgrade are both
exercised for each, and the resulting columns are checked against the model
rather than assumed.

`decision_challenge_events` is `e5c3f18d92ab`, on `d2b8e64af117`, and carries
the unique constraint that makes ledger idempotence a database guarantee rather
than a caller's good intentions.

`d2b8e64af117` backfills every already-sealed row to `reconstructed` rather
than letting it inherit the column default. Nothing about a row sealed by code
that had no concept of capture timing establishes that it preceded the
analysis, and a wrongly-`contemporaneous` row is precisely the claim the column
exists to prevent. One caveat for anyone testing locally: the
migration chain cannot be replayed end-to-end on SQLite, because
`8d92c7f4e1aa` alters constraints in a way SQLite does not support. That is
pre-existing and unrelated; production is Postgres, and local dev provisions
via `create_all` (see `docs/DEVELOPMENT.md`).
