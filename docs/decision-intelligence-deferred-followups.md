# Decision Intelligence — Deferred Follow-ups

> Tracking doc for backend follow-ups deferred out of `feature/expert-reasoning-scorecard`
> (commit `b45fe52` — "Improve decision intelligence scope, routing, and confidence
> calibration"). None of these are launch blockers; they're documented here so they
> don't evaporate once this branch's context rolls off.

---

## 1. Batch grounding flag for connector-fed scoring

**Summary:** The confidence-calibration clamp in `_generate_batch_scorecards`
(`strategy.py`) detects connector/upload grounding by scanning each queued idea's
`description`/`name` text for known context markers (`[Salesforce Context]`,
`[Snowflake Context]`, etc.). In practice this heuristic rarely fires, because the
agent (LLM) synthesizes clean idea descriptions for `queue_scorecards` rather than
forwarding the raw context block — so the marker string doesn't survive into the
batch scorer's input, even when the underlying data genuinely came from a connector.

**Why deferred:** Connector-fed batch scoring (NEXT_STEPS item B4 — "Connectors feed
scoring: use Jira/Salesforce/Snowflake to ground a dimension") is itself a future
capability, not something in production use today. The correct fix is an explicit
grounding flag threaded from the tool-call layer (`ai_agent.py`, which sees the raw
`[...Context]` blocks) through `queue_scorecards` into the batch scorer — replacing
the text-marker heuristic. That plumbing belongs inside the B4 build, not bolted on
ahead of it.

**Risk if ignored:** Low today. Until B4 ships, connector-grounded batch scoring
essentially doesn't happen, so the heuristic's blind spot has little surface. Once B4
lands, if this isn't addressed as part of it, genuinely connector-grounded batch
dimensions could be under-confident (clamped to medium when they should read high) —
safe-direction failure (Article 7), but worth fixing for accuracy once the feature
exists.

**Suggested future owner/tool:** Whoever builds B4 (connector-fed scoring). Likely
Sonnet for implementation, with the grounding-flag design reviewed by Fable given it
touches the same evidence-calibration architecture from this branch.

---

## 2. First-turn `generate_scorecard` exemption

**Summary:** The server-side mutation guard (`_guard_mutation_tool` in `ai_agent.py`)
blocks any non-exempt mutation tool when `user_turn_count <= 1`. `set_scoring_rubric`
and `queue_scorecards` are exempt, so multi-option first-turn scoring works, but
`generate_scorecard` is not exempt — a strict single-idea "score this now" on the
literal first message is still rejected with a confirmation-required error.

**Why deferred:** The First-Turn Decision Contract (added this branch) routes around
this in practice: it instructs the agent to propose a status-quo alternative for any
single-path decision, turning most first-turn requests into a two-option case that
scores via the exempt `queue_scorecards` path. The remaining blocked case — a bare
first message demanding an immediate single-idea score with no sensible alternative —
is rare, and the failure mode is soft (one-turn delay, not a broken promise).
Narrowing the guard safely requires plumbing a new "explicit score request" signal
through the tool-dispatch chain, which is architecture-level work, and the guard is
also part of the prompt-injection defense posture — not something to touch under time
pressure ahead of live sales sessions.

**Risk if ignored:** Low. Narrow edge case, soft failure mode, already routed around
by the contract for the vast majority of real conversations.

**Suggested future owner/tool:** Fable to design the tool-dispatch signal (since it
intersects both the scoring contract and the injection-guard surface), Sonnet to
implement and verify against the existing injection-pattern test cases.

---

## 3. Second batch card invisible on reload

**Summary:** When `/score-batch` scores two or more ideas, the first becomes the
thread's baseline (`session['result']`, one entry in `session['analysis_history']`);
subsequent ideas are persisted via `_create_scenario_record` into a separate
scenarios store. Neither `/api/v1/strategy/scores` nor `/api/v1/ai-agent/threads/<id>`
surfaces the non-baseline card — confirmed twice, in the original baseline test and
again during this branch's verification pass. A user who scores two options and
reloads the workspace may see only one.

**Why deferred:** Tracing the fix requires understanding three separate persistence
paths at once (in-session baseline snapshots read via `_scorecard_snapshot_state`,
`session['analysis_history']`, and the standalone `_load_scenarios`/
`_save_scenarios` store) and how the workspace's read paths reconcile them. This is
real investigation work, not a wording or small-logic fix, and attempting it blind
under this branch's scope risked a regression in a system with three overlapping
storage mechanisms for the same data. NEXT_STEPS item C.8 ("storage swap to
standalone artifacts") is the structural fix that would remove this class of bug
entirely — this item may turn out to be a symptom of that larger gap rather than a
standalone bug.

**Risk if ignored:** Medium. Directly affects the core "score two options and compare
them" loop — the demo path's second step. Worth a dedicated session before it's relied
upon in live sales demos with multi-option decisions.

**Suggested future owner/tool:** Needs a scoped investigation session (Sonnet or
Fable) with the explicit mandate to trace `_create_scenario_record` and confirm
whether this is a listing-level fix or requires the C.8 storage-model swap before any
code changes are attempted.

---

## 4. `/scores` ignores `thread_id`

**Summary:** `GET /api/v1/strategy/scores` (`get_completed_scores` in `strategy.py`)
accepts `sort_by`, `sort_dir`, `category`, `search`, `limit`, and `offset` query
params, but no `thread_id` filter — despite being called with one in practice. The
param is silently accepted and ignored; the endpoint returns every baseline score
across every thread for the authenticated user. This was discovered as a side effect
during this branch's verification (a stale card from an earlier, unrelated thread
appeared mixed into a listing meant to be scoped to one thread).

**Why deferred:** Out of scope for the decision-intelligence branch — this is a
pre-existing API gap unrelated to the scoring-behavior or confidence-calibration work
that branch was chartered to fix. Noted here rather than patched in passing.

**Risk if ignored:** Low-to-medium depending on how the frontend actually consumes
this endpoint. If any UI surface relies on thread-scoped filtering here, it's
currently silently broken (returns unrelated threads' scores instead of an empty or
filtered set). Worth a quick audit of callers before assuming it's cosmetic.

**Suggested future owner/tool:** Codex — this is a small, well-specified backend fix
(add the missing filter parameter) with a mechanical acceptance test, once someone
confirms which frontend surfaces depend on it.
