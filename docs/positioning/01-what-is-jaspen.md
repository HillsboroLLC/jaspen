# What Is Jaspen

Jaspen is not an AI chatbot.

Jaspen is a Decision Intelligence platform: a system for moving from ambiguous human context to a prepared, explainable, executable decision.

A chatbot is primarily a conversational interface. It can summarize, brainstorm, answer questions, and produce persuasive language. Jaspen uses AI conversation, but conversation is only the first layer. The product is built around a decision architecture: user-owned criteria, evidence judgment, confidence calibration, deterministic scoring, transparent reasoning, and execution planning today, with canonical Decision Records and custody architecture forming the foundation for longer-term organizational learning.

The distinction matters because decisions are not the same as answers. A useful answer may be fluent. A useful decision must be structured, inspectable, defensible, and capable of being revisited when evidence changes.

## The Core Difference

Traditional AI assistants usually produce a response.

Jaspen produces a decision artifact.

That artifact is not just prose. Today it can contain the decision statement, options, criteria, weights, evidence, confidence, assumptions, scores, trade-offs, recommendation, and execution plan. The canonical Decision Record extends that foundation into a durable record of what was decided and why.

Throughout this documentation, "the decision artifact" refers to that full structure. It is defined once here so later documents can reference it without reciting it.

## One Decision, End to End

The canonical teaching example used throughout this documentation is deliberately ordinary: **accepting a job offer versus staying in a current role.**

A user pastes the situation — a meaningful raise, a fully onsite schedule, a recent reorganization at the new company, a family that values flexibility. Minutes later, not weeks later, the decision has a structure:

- **The decision:** Take the offer vs. stay in the current role.
- **The rubric (user-owned):** Jaspen proposes criteria; the user reweights them — Financial Impact 25%, Work-Life Flexibility 25%, Career Growth 20%, Stability & Risk 15%, Commute & Logistics 15%. The weights are the user's judgment, made explicit.
- **Evidence grading:** the offer's terms are specific but self-reported — graded medium. "A promotion is possible next year" is an impression — graded low. Nothing is invented, and every grade is visible.
- **Confidence calibration:** the model judges Career Growth at 82, but the evidence behind it is medium, so its contribution is capped at 75. Enthusiasm cannot outrun evidence — mechanically, not rhetorically.
- **Deterministic scoring:** code computes the weighted rollup. Staying scores 72; the offer scores 58 — at medium confidence, with the reason for every point inspectable.
- **The conversation continues:** "What would raise the score?" has a concrete answer — upload the offer letter, and Financial Impact moves from self-reported to verified evidence.
- **The Decision Record:** the final call, the reasoning, the labeled assumptions, and — months later — the outcome and the lesson learned ("a competing offer is negotiating leverage even when you don't take it").

When someone later asks why the answer was 72, there is an answer: the criteria, the weights, the evidence grades, and the math. That is the difference between an answer and a decision you can defend. And the same mechanism, unchanged, scores a board's capital allocation — the framework encodes form, not domain.

## Product Maturity Map

### Current

Jaspen currently supports decision analysis, scorecards, evidence grading, confidence calibration, user-owned rubrics, transparent reasoning, and execution planning.

### Foundation / In Development

Jaspen is formalizing canonical Decision Records, private Decision Record infrastructure, and custody architecture. Private customer-owned records are the default design.

### Future

The public Decision Library, pattern discovery, outcome-based insights, cross-record Decision Intelligence, and broader organizational learning are future layers. They should be described as the Learning System vision, not as fully active production behavior.

## AI Conversation

Jaspen begins in conversation because real decisions rarely arrive neatly packaged. Users bring fragments: goals, constraints, documents, emails, operating data, stakeholder concerns, and partial intuition.

The AI layer helps interview the user, surface missing context, propose a starter rubric when useful, and translate messy inputs into decision structure. It asks the single highest-value next question rather than turning the process into a form or checklist.

Conversation is the intake path, not the whole product.

## Deterministic Scoring

Jaspen does not ask the AI to invent a final score.

AI may judge evidence against a criterion, but published numbers are calculated by deterministic code. Criteria, weights, confidence caps, rollups, categories, tiers, and scenario effects are computed through repeatable mechanisms.

This is a constitutional boundary: models judge; code calculates.

## Evidence Grading

Jaspen treats evidence quality as part of the decision, not as a footnote. Each judgment reflects whether the evidence is strong, inferred, limited, or assumed.

Weak evidence does not stop the process. It lowers confidence. Better evidence raises the confidence ceiling.

This allows users to make progress without pretending uncertainty has disappeared.

## Confidence Calibration

Confidence is not decorative language in Jaspen. It has mechanical consequences.

An optimistic score supported only by assumptions cannot contribute as much as a score supported by strong evidence. Confidence caps prevent enthusiasm, persuasion, or thin evidence from outrunning what is actually known.

The result is not perfect certainty. It is honest decision support.

## Transparent Reasoning

Every number must decompose.

The user can see the criteria, the weight of each criterion, the evidence behind each judgment, the confidence grade, the assumptions, and the way the score was assembled. Jaspen's explainability comes from the decision being built from inspectable parts.

## User-Owned Rubrics

Jaspen may propose criteria, but the rubric belongs to the user.

The user controls what matters, how much it matters, which options are considered, and what decision is ultimately made. Jaspen operationalizes judgment; it does not replace it.

## Execution Planning

A decision is incomplete if it cannot become action.

Jaspen converts decision analysis into execution planning by deriving work from the weak dimensions, risks, recommendations, and constraints surfaced during the decision. The plan is not a generic template. It is the scorecard restated as work.

## Decision Records

The canonical Decision Record is the next durable unit of Jaspen's architecture.

A Decision Record preserves the decision statement, objectives, criteria, weights, alternatives, evidence, assumptions, confidence, recommendation, execution plan, outcome, and lessons learned.

The Decision Record is the durable artifact. The scorecard is one component of it.

## Organizational Learning

Over time, private Decision Records can become organizational memory for the customer that owns them.

They can help teams see what they believed, what evidence they used, which assumptions failed, what outcomes followed, and what patterns may emerge across many decisions. This is the long-term Learning System vision: future guidance improves, but ownership of criteria, weights, and decisions stays with the human.

## Positioning Statement

Jaspen is a Decision Intelligence platform that turns messy context into explainable decisions by combining AI conversation, user-owned rubrics, evidence grading, deterministic scoring, confidence calibration, transparent reasoning, and execution planning, with canonical Decision Records as the foundation for future organizational learning.

In six words: make the call you can defend.
