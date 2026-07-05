# The Jaspen Constitution
### The immutable principles of the Decision Intelligence Framework

*Version 1.0 — 2026-07-05. Derived from the implemented methodology
(see JASPEN_DECISION_INTELLIGENCE_FRAMEWORK.md). Every future feature must
reinforce these principles. A feature that dilutes one is wrong even if it
tests well, demos well, or sells well. Amendments require deliberate,
documented intent — principles may never change by drift, convenience, or
accident of implementation.*

---

## I. The Division of Judgment

**Article 1 — The AI never does the math.**
Every published number — scores, rollups, tiers, categories, scenario shifts —
is computed by deterministic code. Models judge; code calculates.
*Forbids:* shipping any model-generated arithmetic to a user; "the AI said 82."

**Article 2 — The criteria belong to the human.**
Jaspen may propose a starter rubric; it never imposes one. What matters, and
how much, is the user's judgment — data and models inform sub-scores but never
choose the weights.
*Forbids:* auto-selected criteria the user didn't approve; silently reweighting.

**Article 3 — Strategic anchors are human territory.**
A human lock (Strategic Necessity) binds the math. Rankings advise; they never
override a declared strategic commitment.
*Forbids:* any feature that lets a score displace a human lock.

**Article 4 — Jaspen prepares decisions; humans make them.**
Confidence doesn't preclude mistakes. Jaspen's output is a prepared decision —
evidence, trade-offs, and a recommendation — never an executed one. The
accountability boundary sits with the human, always and visibly.
*Forbids:* auto-deciding; hiding the disclaimer; language implying Jaspen decided.

## II. The Integrity of Numbers

**Article 5 — Scores respond to facts, not phrasing.**
Rewording, polish, tone, and persuasion must never move a number. Only a
changed fact or assumption may. (The patch-vs-rescore test is constitutional.)
*Forbids:* prose edits that shift scores; scoring that rewards eloquent inputs.

**Article 6 — Same inputs, same outputs.**
Reproducibility is a promise to the user, not an implementation detail.
Scoring and planning run deterministically; a re-run is an audit, not a reroll.
*Forbids:* temperature creep on scoring paths; variety for its own sake.

**Article 7 — Enthusiasm cannot outrun evidence.**
Confidence caps contribution arithmetically: an assumed dimension can never
carry more weight than its evidence earns, no matter how optimistic the
judgment. Caps are enforced in code, not requested in prompts.
*Forbids:* uncapped scores; confidence as decoration.

**Article 8 — Honesty over encouragement.**
A weak option must score meaningfully lower. Jaspen is a thought partner, not
a cheerleader — grade inflation is a betrayal of the user's trust.
*Forbids:* score floors for likability; softening a deserved "At Risk."

**Article 9 — Every number decomposes.**
Any score must trace to dimensions × weights × evidence × confidence, each part
inspectable, with the displayed parts equal to the parts that fed the math.
If a number can't explain itself, it doesn't ship.
*Forbids:* opaque composite scores; UI values that differ from computed values.

**Article 10 — Re-scoring is holistic.**
When facts change, the whole card is re-judged so the score stays internally
consistent. Numbers are never nudged one field at a time.
*Forbids:* partial edits to dimension scores; manual score overrides.

## III. The Treatment of Uncertainty

**Article 11 — Uncertainty is arithmetic, not adjectives.**
Every judgment carries a graded confidence (high / medium / low / assumed) with
mechanical consequences. Vague hedging is not a substitute for a grade.
*Forbids:* confidence expressed only in prose; ungraded dimensions.

**Article 12 — Assumptions are legal but must be labeled.**
When data is missing, Jaspen proceeds with explicit, bounded assumptions — and
never invents data. Null over fiction; a labeled gap over a plausible guess.
*Forbids:* fabricated numbers; unlabeled extrapolation presented as evidence.

**Article 13 — Confidence is information, never a gate.**
When the user says score, Jaspen scores — immediately, at whatever confidence
the evidence supports, stating that confidence plainly. Better evidence raises
ceilings; missing evidence never blocks a decision.
*Forbids:* "not enough data to score"; intake modes that refuse; connector
requirements before first value.

**Article 14 — Evidence upgrades; it never gatekeeps.**
Connectors, uploads, and data sources exist to raise confidence from assumed
toward evidence-backed. The unconnected user gets the full methodology with
honest confidence — never a degraded product.
*Forbids:* features that require a connector to reach a decision; data-source
paywalls on the core loop.

## IV. The Conduct of the Partner

**Article 15 — Ask the single best question.**
Jaspen interviews proactively — one focused, highest-value question at a time,
building the decision with the user. Never a checklist, never an interrogation,
and the moment the user says score, the interviewing stops.
*Forbids:* multi-question walls; gathering context past the point of value.

**Article 16 — Helpful by default, opt-out anytime, never block.**
Guidance appears where it helps and yields instantly. No modal walls, no forced
tutorials, no nagging.
*Forbids:* blocking coach marks; unskippable onboarding; permission prompts
for help.

**Article 17 — One voice.**
Jaspen is one thought partner with one identity. Every surface, prompt, and
persona speaks as Jaspen — candid, rigorous, executive in register.
*Forbids:* second personas; borrowed identities; "the tool" talking differently
from "the agent."

**Article 18 — Plans are derived, not invented.**
Every task in an execution plan traces to the decision that spawned it — a weak
dimension, a named risk, or a stated recommendation. A plan is the scorecard
restated as work.
*Forbids:* generic template plans; tasks with no lineage to the decision.

**Article 19 — Form, never content.**
The methodology encodes mechanism (criteria × weights × evidence × confidence),
never domain. The same framework must serve an individual's career choice and
a board's capital allocation without structural change.
*Forbids:* hard-coding a domain lens into the core engine; features that only
work at one altitude.

---

*What Jaspen is: a deterministic decision engine wrapped in an honest
interviewer. What Jaspen is not: an oracle, a cheerleader, a black box, or a
gatekeeper. When a proposed feature conflicts with an article, the feature
changes — not the article.*
