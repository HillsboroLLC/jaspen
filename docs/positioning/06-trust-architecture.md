# Trust Architecture

Jaspen's trust model is architectural, not rhetorical.

The product does not ask users to believe a confident AI answer because it sounds polished. It shows how the decision was built, where the evidence is strong, where assumptions remain, how confidence affects the score, and who controls the final judgment.

## Constitution

The Constitution defines the non-negotiable boundaries of the system.

Core principles include:

- Models judge; code calculates.
- Criteria and weights belong to the human.
- Strategic anchors are human territory.
- Jaspen prepares decisions; humans make them.
- Scores respond to facts, not phrasing.
- Same inputs produce the same outputs on scoring paths.
- Confidence is arithmetic, not decoration.
- Assumptions are legal but must be labeled.
- Evidence upgrades; it never gatekeeps.

The Constitution exists to keep product growth from drifting away from trust.

## Deterministic Scoring

Jaspen separates judgment from calculation.

AI may help assess evidence against a criterion, but the scoring mechanics are deterministic. Weights, confidence caps, rollups, categories, tiers, and scenario effects are computed by code.

This makes the published score inspectable and repeatable.

## Evidence Grading

Jaspen grades evidence because decisions are only as strong as their support.

Evidence may be direct, inferred, limited, or assumed. The system shows that distinction plainly. A recommendation built on assumptions can still be useful, but it must not masquerade as certainty.

## Confidence Calibration

Confidence is tied to evidence and enforced through caps.

If a dimension has weak support, its contribution is limited — the cap is enforced in code, not requested in prompts. If better evidence arrives through user input, documents, or connected systems, confidence can improve.

This makes confidence a working part of the decision, not a reassurance phrase.

## Transparent Reasoning

Every important conclusion is explainable through visible parts:

- decision statement
- alternatives
- criteria
- weights
- evidence
- assumptions
- confidence
- raw dimension scores
- capped scores
- rollup
- recommendation
- execution implications

The user never has to reverse-engineer the reasoning from prose.

## Custody Rings

Canonical Decision Records require a custody architecture.

There is one canonical Decision Record schema, but multiple custody levels. One schema does not mean one shared data pool.

### Ring 1: Private Decision Records

By default, every completed Decision Record belongs to the customer.

Private records become part of the customer's organizational memory. They are never published without explicit consent. Enterprise records remain enterprise assets.

### Ring 2: Public Decision Library

Public Decision Records exist only through explicit customer permission.

They must be explicitly opted in and anonymized unless the customer separately approves named attribution. They may become Decision Library entries, starter examples, decision kits, marketing examples, SEO content, AI search content, or educational material.

Publication is always optional.

### Ring 3: Internal Evaluation and Calibration Corpus

Jaspen may use appropriately governed, non-identifying Decision Records for internal evaluation, calibration, testing, and future learning.

The purpose is improving confidence calibration, evaluation datasets, prompt evaluation, constitutional compliance, and Decision Intelligence. This corpus is not customer-facing and should not expose identifiable customer information.

## Privacy

Privacy is a default, not an upsell.

The user's decision context, records, documents, connected data, and outcomes are treated as customer-owned material. Public reuse requires permission. Internal learning requires governance.

## Governance

Governance matters because decisions can carry financial, operational, legal, strategic, and reputational consequences.

Jaspen's governance posture makes clear:

- who owns the decision
- who owns the rubric
- who can access the record
- whether the record is private, public, or internally governed
- what evidence supported the decision
- what assumptions remained
- what confidence was warranted
- what changed after execution

## Where Machine Learning Fits

Machine learning has a place in Jaspen's future — and a fence around it.

ML may eventually improve pattern discovery across governed records, sharpen confidence calibration against outcome history, and make future guidance more relevant: better questions, better proposed criteria, better comparisons.

ML never overrides the Constitution. It does not perform published scoring — deterministic code does. It does not choose or reweight the user's rubric. It does not upgrade evidence grades or lift confidence caps. It does not make the decision.

The boundary in one sentence: machine learning may inform what Jaspen notices; it may never touch your weights, your scores, or your decision.

## Hallucination Resistance

Jaspen does not eliminate AI hallucinations.

No AI system should be described as incapable of hallucinating. Jaspen is designed to resist unsupported conclusions through constitutional constraints, deterministic scoring, evidence grading, confidence caps, user-owned rubrics, labeled assumptions, and transparent reasoning. User data, documents, and connected context can improve grounding when available, but they do not make hallucinations impossible.

The claim is not "Jaspen cannot hallucinate."

The defensible claim is: Jaspen is built to resist and constrain unsupported AI output, and to show the user where evidence is strong, weak, or assumed.
