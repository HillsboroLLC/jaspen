# The Jaspen Decision Intelligence Framework
### Foundational Design Specification — reverse-engineered from the implementation

*Version 1.0 — captured 2026-07-05 from the codebase as source of truth.*
*This document records how Jaspen actually thinks today. File and line references point to the implementing code. It is a description, not a proposal.*

---

## 1. Core Philosophy

### 1.1 The problem
Organizations do not lack ideas, data, or opinions — they lack a **repeatable way to move from a pile of unstructured context to a decision people can stand behind**. The homepage states the pain register exactly (`frontend/src/homeSections/HomePage/BeforeAfter.jsx`): notes, emails and opinions with no structure; stakeholders who find out later and push back; decisions made by gut feel, the loudest voice, or "whoever made the deck"; days of back-and-forth with no resolution; decisions nobody fully owns.

Jaspen's answer: *"Paste your notes, emails, or data — Jaspen will help determine the path forward."* The product converts raw human context into a **scored, explainable, executable decision** in one continuous conversation.

### 1.2 What differentiates Jaspen from a general-purpose AI assistant
The architecture encodes four commitments a chat assistant does not make:

1. **The AI never does the math.** Model output is evidence-judgment only; every published score is computed in Python (`_recompute_jaspen_score`, `strategy.py`). *"This removes LLM arithmetic drift and guarantees the published caps are actually enforced"* (docstring, strategy.py:2092).
2. **Same inputs, same outputs.** Scoring and planning calls run at temperature 0 with determinism stated as a contract in the prompt itself: *"Temperature is 0 — be deterministic and evidence-based"* (scorecard prompt); *"DETERMINISM: Given the same scorecard, scenario, and instruction, produce the SAME plan every time"* (WBS prompt).
3. **Uncertainty is first-class and load-bearing.** Every judged dimension carries a confidence grade that mechanically caps its contribution to the score (§3.3). A general assistant expresses uncertainty in prose; Jaspen expresses it in arithmetic.
4. **The criteria belong to the human.** The agent's system prompt is explicit: *"You MAY propose a sensible starter rubric for them to approve or edit, but it is THEIRS — never impose criteria"* (ai_agent.py:558). Jaspen is a thought partner operationalizing the user's judgment — not an oracle replacing it.
5. **Learning is accumulated transparently.** A decision is not only an answer in the moment; once completed, it can become a Decision Record, then part of a Decision Library, then evidence for pattern discovery. Jaspen learns as an institution learns: by preserving reasons, outcomes, and lessons in human-readable form — never by secretly changing the user's criteria, weights, or decision.

### 1.3 The FLOW Method™
The public articulation of the methodology (homepage, `FlowIllustrated.jsx`): **Frame → Limits → Opportunities → Weigh** — "One flow. Full context. Zero handoffs." Four questions worked through conversationally, each building on the last: where are we going (Frame), what constrains us (Limits), what could we do (Opportunities), and how do the options compare (Weigh). The backend realizes FLOW as: intake interview → constraint and stakeholder capture → option enumeration → weighted, confidence-capped scoring → trade-off analysis → execution plan.

### 1.4 Operating principles (as implemented)
- **Proactive interviewer, not passive scorer.** The agent leads "a short guided survey" — focused, one-at-a-time questions — to build scoring *with* the user (system prompt: "ask the single highest-value next question, not a checklist").
- **Confidence is informational, never a gate.** *"When the user asks you to score… do it immediately. NEVER refuse, defer, or say you are 'in intake mode'"* (system prompt, rule 2). Better evidence raises confidence; missing evidence never blocks a decision.
- **Helpful by default, opt-out anytime, never block** (product-wide UX principle; visible in the non-blocking adaptive coach and the disclaimer rendered beside scores: "Confidence doesn't preclude mistakes").
- **Honesty over encouragement.** Batch prompt: *"Do not inflate scores — a weak option must score meaningfully lower."*
- **Facts move numbers; prose never does.** The patch-vs-rescore decision test (§2.4).

---

## 2. Decision Methodology

### 2.1 Stages of the decision process
As implemented across `strategy.py` / `ai_agent.py`:

| Stage | What happens | Where |
|---|---|---|
| **1. Intake / Frame** | User pastes context or describes the problem; agent interviews one question at a time; objective lens selected (balanced / cost / speed / growth) | agent system prompt; `STRATEGY_OBJECTIVE_OPTIONS` (strategy.py:59) |
| **2. Criteria formation** | Default 6-dimension rubric, objective-tilted weights, or a fully user-defined rubric (2–12 weighted criteria) | `_DIM_WEIGHTS` (strategy.py:2228); RUBRIC_ENGINE_SPEC |
| **3. Evidence judgment** | Model scores each option on each criterion (0–100) with a confidence grade and a specific rationale ("the put or take") | `_generate_jaspen_scorecard` (2335); batch dossier (2666) |
| **4. Deterministic rollup** | Python caps by confidence, weights, averages, categorizes | `_recompute_jaspen_score` (2092) |
| **5. Trade-off / Weigh** | Tiering, key differentiator, per-option strongest/weakest, portfolio recommendation and sequence | batch dossier `portfolio_summary`; portfolio agent (3524) |
| **6. Scenario exploration** | What-if lever changes recomputed **deterministically in Python** — no model call for the score shift | `_LEVER_SENSITIVITY` engine (5262) |
| **7. Execution planning** | Scorecard mechanically converted to a phased WBS | WBS prompt (4730) |
| **8. Execution & sync** | Plan pushed/synced to Jira/Smartsheet; status flows back; connector health monitored | `jira_sync.py`, `smartsheet_sync.py`, `connector_monitor.py` |
| **9. Memory** | Completed projects mined for reusable organizational learning | memory-extraction prompts (ai_agent.py:1640, 10742); org idea ledger |

### 2.2 Information flow
Conversation, uploads, and connector context blocks (`[Snowflake Context]`, `[Salesforce Context]`…) flow **into** evidence judgment. The agent is mandated to *use* attached data immediately: *"Do not ask the user for data you already have. Do not say you cannot access data"* — identify numeric columns, compute, name actual values, cite table/column names (system prompt, DATA ANALYSIS MANDATE). Judged evidence flows into the deterministic rollup; scores flow into tiers, trade-offs, scenarios, and plans. Nothing user-facing is produced directly by raw model arithmetic.

### 2.3 Uncertainty and assumptions
Uncertainty is graded per dimension on a four-level evidence scale (scorecard prompt):
- **high** — evidence from the conversation
- **medium** — reasonable inference
- **low** — limited signal
- **assumed** — no direct evidence; extrapolated from patterns

Assumptions are legal but must be **labeled and bounded**: *"If data is incomplete, state what is missing and proceed with clear, labeled assumptions"*; *"Use null only when information is genuinely absent — never invent data"*; *"Every numeric field must be an actual number, not prose."* When the user asks how to improve confidence, the agent must answer with 1–3 ranked, specific actions naming the dimension, the data source, and the estimated confidence gain (e.g., "Connecting your CRM would move Financial Viability from assumed to evidence-backed, likely pushing it from 58 to 75+").

### 2.4 The fact/prose boundary (patch vs. re-score)
A codified decision test governs when numbers may move (agent system prompt): *"Does this change any FACT or ASSUMPTION the score depends on?"*
- Wording, tone, clarity, length → `patch_scorecard`; **"the numbers MUST NOT move."**
- Changed budget, timeline, team, market, pricing → `generate_scorecard` with `rescore_scorecard_id`: the same idea is re-scored **holistically, in place** — never partially edited — so the score stays internally consistent.
- Ambiguous → treat as wording. New idea or keep-alongside variant → new scorecard.

This is the methodology's integrity rule: scores respond to facts, never to persuasion or polish.

### 2.5 Trade-offs and prioritization
Options are tiered by deterministic thresholds on the computed score (strategy.py:2801): **Leading Candidate** (≥78), **Secondary Candidate** (≥68), **Monitor / Niche** (<68). A fourth tier, **Strategic Necessity**, is human-reserved: options the user LOCKS are included regardless of rank — encoding the principle that *strategic anchors are a human decision the math must respect, not produce*. The dossier also assigns each option a `primary_role` (the job it would do in the portfolio) and produces a `portfolio_summary` with a `recommended_sequence` — commit / develop next / monitor, in order — so the output is a portfolio posture, not a single winner.

---

## 3. Scoring Framework

### 3.1 The default dimensions
Six standard dimensions (strategy.py:2228): **market_opportunity, financial_viability, execution_readiness, strategic_alignment, risk_profile, evidence_quality.** The sixth is notable IP: *the quality of the evidence itself is a scored dimension* — a decision built on thin support is penalized for that thinness, transparently.

### 3.2 Weighting philosophy
Weights express **strategic intent, not truth**. The user's objective selects a weight profile (`_DIM_WEIGHTS`):

| Dimension | cost_optimization | growth | operational | innovation | balanced |
|---|---|---|---|---|---|
| market_opportunity | .12 | **.25** | .10 | .22 | .18 |
| financial_viability | **.25** | .18 | .18 | .15 | .20 |
| execution_readiness | .20 | .20 | **.28** | .18 | .18 |
| strategic_alignment | .15 | .15 | .18 | **.20** | .16 |
| risk_profile | .20 | .12 | .18 | .15 | .16 |
| evidence_quality | .08 | .10 | .08 | .10 | .12 |

An objective-guidance clause tilts the *narrative* the same direction as the weights (`_scorecard_objective_guidance`). With a custom rubric, the user's own weights replace the profile entirely (2–12 criteria; weights sum to 1.0 ±0.02, renormalized proportionally; each criterion keyed by slug with an `is_risk` display flag; "100 = best for that criterion" stated as a convention, including for cost-type criteria).

### 3.3 Confidence methodology — the signature mechanism
`_CONFIDENCE_CAPS = {"high": 100, "medium": 75, "low": 60, "assumed": 45}` (strategy.py:2080).

A dimension's judged score is **capped at its confidence ceiling before weighting**: an "assumed" dimension can never contribute more than 45 points regardless of how optimistic the judgment was. The capped value is written back so *the dimension bar the user sees matches what actually fed the score* (comment at 2123). Display confidence percentages (`_DIMENSION_CONFIDENCE_PCT`: high 92 / medium 70 / low 48 / assumed 30) communicate the same grades numerically. The philosophical claim: **enthusiasm cannot outrun evidence, by construction.**

### 3.4 Deterministic calculations
- **Rollup:** capped, weighted average across dimensions → overall score → category by fixed thresholds (`_scores_category_from_values`): ≥80 **Excellent**, ≥60 **Good**, ≥40 **Fair**, else **At Risk**.
- **Scenario engine** (strategy.py:5262, headed "DETERMINISTIC SCORING ENGINE"): what-if levers map to component sensitivities in a fixed table — e.g. `budget → financial_health ×0.50 + execution_readiness ×0.20`; `timeline → execution_readiness ×0.45`; `penetration → market_position ×0.45` — with fixed component weights. **Scenario score shifts involve no model call at all**: the AI proposes lever framings; arithmetic produces consequences.
- **Tiering, locking, category mapping:** thresholds and overrides in code (§2.5).

### 3.5 Division of judgment
| Actor | Owns |
|---|---|
| **Human** | The decision itself; criteria and weights; the objective lens; strategic locks (Strategic Necessity); whether to accept, edit, or re-score; final accountability ("Confidence doesn't preclude mistakes") |
| **AI** | Evidence judgment per criterion (score + confidence + specific rationale); interviewing to surface missing context; narrative synthesis; proposing (never imposing) starter rubrics; pressure-testing plans ("identify the weakest assumption, the highest-leverage change, and one measurable checkpoint") |
| **Code** | All arithmetic: caps, weights, rollup, categories, tiers, scenario shifts, plan validation. The parts that must be identical every time. |

### 3.6 Where explainability comes from
Every number decomposes: overall score → weighted dimensions → per-dimension raw score, confidence grade, cap applied, one-line rationale ("the put or take"), and `what_would_improve`. Weights are visible and user-owned; thresholds are fixed; the rollup is inspectable code. Explainability is not a feature added on top — it is a *byproduct of the score being assembled from explainable parts*.

---

## 4. Execution Planning Framework

### 4.1 From scorecard to plan
Plans are **derived from the decision, mechanically** (WBS prompt, strategy.py:4730, temperature 0). The generation rules constitute the methodology:
- For **each dimension scoring below 75** → at least one remediation task naming the weak dimension and the specific gap it closes; *lower score = higher priority*.
- For **each top risk** → a mitigation task naming the risk **and its owner**.
- For **each key recommendation** → a task that operationalizes it.
- Dimensions **at/above 75 are strengths** — used to sequence and de-risk, never to generate busywork.
- Anti-generic mandate: *"Every task title must be specific to THIS initiative — no generic titles like 'Research' or 'Planning'."*

The plan is therefore an **argument in task form**: this is what the scorecard says is weak, risky, and promised — and here is the work that answers each item.

### 4.2 Phase logic and shape
10–18 tasks across 4–6 phases following a fixed arc: **Discovery → Planning → Build/Execute → Validate → Launch → Operate.** Each task carries a structured taxonomy: `priority`, `estimated_days`, `suggested_role`, `function` (PMO/Finance/Operations/HR/IT/Marketing/Sales/Product/Legal/Security/Other), `activity_type` (governance/planning/delivery/risk_management/financial_modeling/change_management/training/integration/quality/reporting/other), `dependencies` (by task id), and `risk_area` — *which component score this task addresses*, keeping the plan traceable back to the decision.

### 4.3 Decision gates and lifecycle
The scorecard→plan→(re-plan) loop has one formal gate today: the human accepts, edits (via the plan-editor prompt, strategy.py:8794), or regenerates. Executed plans render in three synchronized views — List (by phase), Board (Kanban by status: To Do / In Progress / Blocked / Done), Timeline (Gantt) — and sync bidirectionally with execution systems (§5), where real-world status becomes the ongoing gate.

---

## 5. Connector Intelligence

### 5.1 The role of external data
Connectors exist to **upgrade the evidence grade of a dimension**, not to make decisions: grounding "a dimension: 'look in the database and answer this,' then score with that evidence (raises confidence from assumed → evidence-backed)" (NEXT_STEPS B4). The doctrine, as designed: **connectors refine, they never gate** — an unconnected user gets a full decision with honest "assumed" confidence; a connected user gets the same decision with harder evidence and higher confidence ceilings.

Two connector classes (connector_registry.py): **execution** connectors (Jira, Smartsheet — bidirectional plan sync) and **data** connectors (Salesforce, Snowflake — evidence for judgment; Oracle Fusion, ServiceNow, NetSuite staged as `coming_soon`).

### 5.2 What strengthens confidence
Governed, queryable, attributable data: pipeline patterns (Salesforce), KPI/financial trend tables (Snowflake), sprint/delivery status (Jira/Smartsheet), plus user uploads (Word/Excel/PowerPoint). The agent must cite table/column names and actual values when it uses them — evidence is *named*, never vaguely absorbed.

### 5.3 What must never override human judgment
Encoded boundaries:
- **Criteria and weights** — data informs sub-scores; it never chooses what matters.
- **Strategic locks** — a LOCKED option is Strategic Necessity regardless of what any dataset says.
- **Conflict resolution is a policy the human selects**, not an automatic override: `latest_wins`, `prefer_external`, `prefer_jaspen`, `manual_review` (connectors status API) — with read/write access and sync mode (`import` / `push` / `two_way`) equally user-governed per connector.
- **Credential trust**: tokens Fernet-encrypted with key versioning; health monitoring and audit endpoints per connector.

---

## 6. Enterprise Decision Model — one methodology, every altitude

The same primitive — *options, judged on weighted criteria, with confidence-capped evidence, rolled up deterministically, converted to sequenced work* — recurs at every organizational level. Nothing changes but the objects being scored and the weight-setter's altitude.

| Level | The decision objects | How the framework serves them (existing machinery) |
|---|---|---|
| **Individual** | Personal/professional choices, one idea at a time | Full intake→scorecard→plan loop solo; private visibility; free tier; Pluto-class model |
| **Project manager** | Task sequencing, scope trade-offs, vendor picks | Execution tab (List/Board/Timeline); Jira/Smartsheet two-way sync; WBS taxonomy speaks PM language (functions, dependencies, phases) |
| **Transformation leader** | Competing initiatives, portfolio sequencing | Batch dossier + tiers + `recommended_sequence`; scenario levers (budget/timeline/penetration); Lean-style remediation tasks per weak dimension |
| **Director** | Team-level prioritization, resource allocation | Organizations, seats, shared visibility (`shared_with_user_ids`); org idea ledger; team routes; custom rubrics encode the department's definition of value |
| **Executive** | Cross-functional bets, operating model shifts | Objective lenses as strategy dials (cost/speed/growth); portfolio agent across scorecards; "Recommendation, Why now, Financial impact range, Key risks, Next 2 actions" as the default decision structure |
| **CEO** | The few decisions that shape the year | Strategic Necessity locks; portfolio posture over single winners; confidence-weighted honesty about what's actually known |
| **Board** | Ratification, oversight, defensibility | Explainable decomposition of every number (§3.6); audit events; exports (PDF/Excel/Word); the deterministic guarantee — the score is reproducible math over stated evidence, not an AI's mood |

**Why it scales naturally:** the framework never encodes *content* — only *form* (criteria × weights × evidence × confidence). A PM's rubric and a board's rubric differ in every input and in no mechanism. Trust also composes upward: because each score decomposes into dimensions, rationales and confidence grades, a director can defend a team's ranking to an executive using exactly the artifact the analyst produced — the methodology *is* the communication protocol between levels. Admin policy, org membership, MFA policy, and plan-gated model tiers (Pluto/Orbit/Titan) provide the governance shell around the same core.

---

## 7. Jaspen as a Learning System

The next stage of the framework is not a claim about any one technical
category. It is **organizational learning made explicit**. Jaspen becomes a
Learning System by preserving completed decisions, curating them into reusable
knowledge, discovering patterns across them, and applying those patterns
transparently to future decisions. The implementation can change over time; the
philosophy should not.

The constitutional boundary remains unchanged: **the user owns criteria,
weights, and the final decision.** Learning improves guidance. It never
automates judgment.

### 7.1 Level 1 — Decision Records

Every completed decision should be capable of becoming a structured Decision
Record. The record captures what was decided, why it was reasonable at the
time, what evidence supported it, how confident Jaspen was, what work followed,
what happened afterward, and what was learned.

A mature Decision Record includes:

- decision statement
- objectives
- criteria
- weights
- alternatives
- evidence
- confidence
- recommendation
- execution plan
- eventual outcome
- lessons learned

This is the smallest durable unit of Decision Intelligence. It preserves the
reasoning, not just the result. A decision record lets a team ask, months later:
what did we believe, what did we know, what did we assume, what did we choose,
and what did reality teach us?

The record must remain human-readable. It is organizational memory, not hidden
model state.

### 7.2 Decision Record Custody

The Learning System depends on a permanent trust architecture around customer
decisions. Jaspen can have one canonical Decision Record schema while honoring
multiple custody levels. The same structured record may serve different
purposes only when its custody ring permits that use.

Custody is not a storage detail. It answers three constitutional questions:

- who owns the record;
- who may see it;
- what it may be used for.

#### Ring 1 — Private Decision Records

Every completed decision belongs to the customer. By default, every Decision
Record is private.

Private Decision Records become part of the customer's organizational memory:
the durable record of what was decided, why, with what evidence, at what
confidence, and with what later outcome. For individuals, this is personal
decision memory. For companies, it is enterprise knowledge.

Private records are never published without explicit consent. Enterprise
records remain enterprise assets. Jaspen may help structure, retrieve, and
learn within the customer's own environment, but custody remains with the
customer.

#### Ring 2 — Public Decision Library

Public Decision Records exist only through explicit customer permission. Public
records must be anonymized and prepared for human reading before they become
Library material.

With permission, public records may become:

- Decision Library entries
- Starter Templates
- Decision Kits
- marketing examples
- SEO
- AI search
- educational content

Publication is always optional. A customer can receive the benefit of Jaspen as
a Learning System without turning their decisions into public examples.

#### Ring 3 — Internal Evaluation & Calibration Corpus

Jaspen may use appropriately governed Decision Records for internal evaluation,
calibration, testing, and future learning. The purpose is to improve:

- confidence calibration
- evaluation datasets
- prompt evaluation
- constitutional compliance
- Decision Intelligence

This corpus is never customer-facing. It does not become marketing material,
public Library content, or a visible starter example. It must not expose
identifiable customer information.

The internal corpus exists to make Jaspen more reliable and more faithful to
its Constitution. It does not change the ownership of the original decision.

### 7.3 Level 2 — Decision Library

Decision Records can become a curated Decision Library: a body of reusable
decision knowledge for the organization and, where appropriate, for the market.
The Library serves:

- onboarding
- starter templates
- decision kits
- SEO
- AI search optimization
- marketing
- customer education
- reusable frameworks
- calibration
- future evaluation

The Library is not a pile of transcripts. It is a selective, readable collection
of decisions whose structure makes them teachable. A strong Library helps a new
employee understand how the organization reasons. It helps a customer understand
what good decision-making looks like. It helps Jaspen propose better starter
rubrics while still asking the user to approve or edit them.

The Library is accumulated decision knowledge. It is not a precedent engine
that binds the next decision.

### 7.4 Level 3 — Pattern Discovery

Across many Decision Records, Jaspen can discover patterns:

- common success factors
- common failure modes
- hidden trade-offs
- sensitivity relationships
- recurring blind spots
- evidence that changes outcomes
- long-term outcome trends

Patterns are advisory evidence. They may help Jaspen ask a better question,
flag a fragile assumption, propose a more relevant criterion, or explain why a
past decision is comparable. They must never replace the user's judgment.

This is where the Constitution's **Propose, Never Impose** doctrine matters
most. A pattern may inform a recommendation; it may not silently reweight the
rubric, change the score, or declare the decision for the user.

Pattern discovery must respect custody. Private records may inform only the
customer's own organizational learning unless governed permission allows a
broader use. Public Library records may inform public examples. Internal
evaluation records may improve calibration and compliance without exposing
customer identity or customer-facing content.

### 7.5 Level 4 — Decision Intelligence

Decision Intelligence is the application of accumulated learning to future
decisions. Future users benefit from prior decisions because Jaspen can surface
relevant patterns with context and limits:

> In similar decisions, users who weighted manager quality more heavily
> experienced better long-term outcomes.

That sentence is only constitutional if the recommendation is transparent:
what decisions were similar, what outcome improved, how strong the evidence is,
and what remains under the user's control. The user always controls:

- criteria
- weights
- decision

Nothing becomes automatic. Nothing secretly adjusts scoring. Nothing hides the
reason a comparison is being made. Learning improves the quality of guidance,
questions, examples, and calibration; it never overrides human ownership.

### 7.6 Relationship to Confidence and Calibration

Learning strengthens the confidence system without dissolving it. Outcomes can
help Jaspen understand when "medium" evidence was reliable, when assumptions
were too optimistic, and which evidence sources actually changed outcomes. This
can improve future calibration, but only through visible methodology: named
evidence, stated confidence, inspectable reasoning, and user-approved weights.

The long-term advantage is not that Jaspen becomes more automatic. It is that
Jaspen becomes more honest about what prior decisions teach.

Custody strengthens calibration by separating customer memory, public education,
and internal evaluation. A record can help improve confidence methodology
without becoming public content, and a public example can teach without
revealing a customer's identity.

### 7.7 Future evolution

Because the framework is constitutional rather than implementation-specific,
Jaspen can evolve across many technical eras. Records may be stored differently,
libraries may be curated differently, pattern discovery may improve, and
evaluation may mature. The enduring promise is stable:

- completed decisions become durable knowledge;
- durable knowledge has explicit custody;
- durable knowledge becomes a readable Library;
- the Library enables pattern discovery;
- discovered patterns inform future guidance;
- the human still owns the rubric and the decision.

## 8. Future Vision — the Decision Operating System

Everything below is a natural extrapolation of machinery that already exists; none of it requires abandoning the present architecture.

1. **The decision ledger becomes institutional memory.** Decision Records and the org idea ledger turn completed projects into a queryable corpus — "what did we believe when we chose X, and which assumptions failed?" Decision quality becomes measurable and coachable.
2. **Custody becomes part of the product's trust architecture.** Private records remain customer memory, public records require permission and anonymization, and internal evaluation records improve calibration without becoming customer-facing. This is how Jaspen learns without treating customer decisions as public property.
3. **The Decision Library becomes a growth asset.** Curated records become onboarding material, starter templates, decision kits, customer education, search-visible methodology, and future evaluation sets. The Library is both product surface and intellectual property.
4. **Calibration closes the loop.** With outcomes recorded against confidence grades, the caps (100/75/60/45) evolve from sensible constants into *empirically calibrated* instruments — per organization, per domain. "Jaspen's 'medium' means 71% hit rate in your org" is a sentence no competitor can say without this architecture.
5. **Pattern discovery makes prior judgment useful.** Common success factors, failure modes, hidden trade-offs, sensitivity relationships, recurring blind spots, and outcome trends become visible to future users without becoming automatic rules.
6. **Living plans.** Jira/Smartsheet sync already carries status back. The extrapolation: plan-drift detection, automatic re-scoring when execution evidence contradicts scoring-time assumptions, and re-sequencing recommendations — Weigh flowing continuously back into Frame.
7. **The evidence mesh.** Connector context blocks generalize: any governed source can ground any criterion, with provenance. Evidence-quality scoring (already a dimension) becomes the gatekeeper for what counts as "high" confidence — an auditable chain from board-level score to source row.
8. **Portfolio as the default view.** The dossier's roles, tiers, sequence, and locks mature into standing portfolio governance: rolling re-scores as evidence changes, scenario-tested robustness bands, and organizational weight profiles as explicit strategy documents — the operating model rendered as numbers.
9. **The methodology as protocol.** Because scores are deterministic and decomposable, they can cross org boundaries: a supplier's scorecard, a due-diligence target's portfolio, a subsidiary's rubric — exchanged, verified, and re-computed. FLOW becomes to decisions what double-entry became to accounting: the shared grammar that makes institutions legible.

---

## Appendix A — Implicit assumptions and inconsistencies to formalize
*Recorded for future methodology governance; not critique, and not implementation guidance.*

1. **Two objective vocabularies coexist**: user-facing `STRATEGY_OBJECTIVE_OPTIONS = (balanced, cost, speed, growth)` and the weight-table keys `(cost_optimization, growth, operational, innovation, balanced)`. The mapping between them (and the status of `operational`/`innovation` profiles) is implicit and should be stated canonically.
2. **Two scoring registers exist**: the single-scorecard prompt carries a commercialization framing (EBITDA protection, ROI, time-to-market), while the batch dossier is rubric-neutral. RUBRIC_ENGINE_SPEC already declares the intended unification; the methodology should state when each register applies.
3. **Two dimension sets coexist**: the six-dimension rubric and a legacy four-component mirror (`financial_health`, `operational_efficiency`, `market_position`, `execution_readiness`) kept in sync via `_COMPONENT_DIMENSION_MIRROR` and used by the scenario lever engine. The canonical set — and the lever engine's relationship to the six dimensions — should be made explicit.
4. **Threshold provenance**: tier cut-offs (78/68), category bands (80/60/40), confidence caps (100/75/60/45), and the WBS remediation trigger (<75) are asserted constants. Formalizing *why these numbers* (and per-org configurability policy) belongs in the methodology.
5. **The 10–18 task / 4–6 phase plan envelope** is a fixed shape independent of initiative scale — an implicit "one plan size" assumption the methodology should either endorse or scope.
6. **Confidence grades are AI-attested.** The model both judges a dimension and grades its own evidence; the cap system disciplines the consequence, but the grading itself is self-reported. The methodology should state this and its intended evolution (connector-verified grading).
7. **A second persona ("Kii") persists in legacy tool prompts** (`chat.py`) alongside the Jaspen identity — the canonical voice should be formalized as part of the methodology's identity layer.
8. **The disclaimer doctrine** ("Confidence doesn't preclude mistakes. Please verify important details") functions as the liability boundary of the whole framework and deserves elevation from UI copy to stated principle: *Jaspen prepares decisions; humans make them.*

---

*End of specification.*
