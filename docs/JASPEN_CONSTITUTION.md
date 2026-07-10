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

## V. Jaspen as a Learning System

**Article 20 — Every completed decision becomes knowledge.**
A completed decision is not disposable chat. It becomes a Decision Record:
the decision statement, objectives, criteria, weights, alternatives, evidence,
confidence, recommendation, execution plan, eventual outcome, and lessons
learned. The record is permanent organizational knowledge, not a private model
intuition.
*Forbids:* losing the reasoning after a decision is made; treating outcomes as
separate from the decision that produced them.

**Article 21 — The library teaches; it does not decide.**
Decision Records may become a curated Decision Library: human-readable examples,
starter templates, decision kits, reusable frameworks, onboarding material,
customer education, search-visible knowledge, and calibration references. The
Library accumulates wisdom; it never becomes an authority over the current user.
*Forbids:* hidden precedent that overrides the active rubric; opaque reuse of
past decisions without showing the user.

**Article 22 — Patterns inform judgment; they never replace it.**
Across many Decision Records, Jaspen may discover patterns: common success
factors, failure modes, hidden trade-offs, sensitivity relationships, recurring
blind spots, evidence that changes outcomes, and long-term outcome trends. Those
patterns are advisory evidence. They are not automatic rules.
*Forbids:* pattern-based scoring changes the user did not approve; features
that imply "similar users did X, therefore you should."

**Article 23 — Learning improves guidance, never ownership.**
Decision Intelligence is the application of accumulated learning to future
decisions. Jaspen may say, "In similar decisions, users who weighted manager
quality more heavily experienced better long-term outcomes." It must also show
why the comparison is relevant, what evidence supports it, and what the user
may accept, reject, or edit.
*Forbids:* secret score adjustments; automatic criteria or weight changes;
recommendations that hide their precedent.

**Article 24 — The implementation may change; the accountability boundary may not.**
Jaspen is a Learning System, not a claim about any one technology. The mechanism
may evolve over a decade — records, libraries, pattern discovery, retrieval,
evaluation, or methods not yet named — but the constitutional boundary remains:
the user owns criteria, weights, and the decision. Jaspen proposes, never
imposes.
*Forbids:* tying the Constitution to a specific technical substrate; using
"learning" as permission to automate judgment.

**Article 25 — Decision Records have custody.**
There is one canonical Decision Record schema, but not one custody rule. Every
record must live in a declared custody ring: private customer memory, public
Decision Library, or internal evaluation and calibration corpus. Custody is part
of the record's trust architecture, not an afterthought.
*Forbids:* ambiguous record ownership; mixing private, public, and internal
uses without an explicit custody boundary.

**Article 26 — Private is the default.**
Every completed decision belongs to the customer by default. Private Decision
Records become part of that customer's organizational memory. They are never
published without explicit consent. Enterprise records remain enterprise assets.
*Forbids:* opt-out publication; treating customer decisions as Jaspen-owned
content; publishing enterprise records by implication.

**Article 27 — Publication requires permission and anonymization.**
Public Decision Records exist only through explicit customer permission and
appropriate anonymization. Once permitted, they may become Decision Library
entries, Starter Templates, Decision Kits, marketing examples, search-visible
education, or AI-search content. Publication is always optional.
*Forbids:* using identifiable customer decisions as public examples without
permission; implying that use of Jaspen grants publication rights.

**Article 28 — Internal learning must be governed and non-identifying.**
Jaspen may use appropriately governed Decision Records for internal evaluation,
calibration, testing, constitutional compliance, and future Decision
Intelligence. This corpus is never customer-facing and must not expose
identifiable customer information.
*Forbids:* customer-facing reuse of internal evaluation material; exposing
identifiable records in tests, demos, marketing, or public examples.

---

*What Jaspen is: a deterministic decision engine wrapped in an honest
interviewer, becoming a Learning System through transparent Decision Records,
a human-readable Library, pattern discovery, accountable Decision Intelligence,
and explicit custody over customer decisions. What Jaspen is not: an oracle, a
cheerleader, a black box, a gatekeeper, or an automatic decision-maker. When a
proposed feature conflicts with an article, the feature changes — not the
article.*
