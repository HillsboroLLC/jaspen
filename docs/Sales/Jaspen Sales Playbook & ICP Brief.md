# Jaspen Sales Playbook & ICP Brief

*Implementation stamp: prompt `qualification-v3.1` / rubric `jaspen-rubric-v3.1`, deployed and validated 2026-08-26. Configuration changes are versioned so historical scores stay reproducible; records keep the version they were scored under.*

**Status:** Source of truth for sales, marketing, qualification, and AI-assisted research. Supersedes ad-hoc persona language in campaign docs and job postings.
**Owner:** Founder (Lydia Bailey)
**Last updated:** 2026-08-27
**Sourced from:** jaspen.ai (homepage, pricing, advisory offerings, executive partnership intake), `docs/positioning/*`, `docs/utilities/outcome-pain-research.md`, `docs/utilities/jaspen-benchmark-research.md`

**Rules for using this document:**
1. Everything in §1–§11 is approved for external use as written, with one exception: outcome claims are tiered in §5 and **only Tier A may be stated as fact**.
2. Follow the language guide below. Never describe Jaspen as a "SaaS product," a "chatbot," or a "framework."
3. **No invented proof.** We have no published customer results, ROI multiples, logos, or traction figures. Do not imply them. Industry benchmarks (§5, Tier C) size the *problem* and must always be attributed to their source.
4. Respect the maturity line in §1. Do not sell the Decision Library, pattern discovery, or cross-record organizational learning as available.
5. Keep **product-led acquisition** separate from **enterprise/advisory qualification**. A person can be an excellent self-serve Jaspen user without meeting the enterprise Company Fit criteria in §12.
6. For enterprise/advisory opportunities, continue to qualify on **two independent axes** — Company Fit and Purchase Readiness (§12). Never collapse them into one score.

### Core sales philosophy: put Jaspen in the path of the decision — let the product create the proof

This is the organizing principle of the motion. Jaspen is built to demonstrate value through interaction, so the default acquisition path should not require a discovery call, founder demo, or sales conversation.

The first objective is to identify a person who is likely to be facing a consequential decision, trade-off, prioritization challenge, investment choice, resource-allocation question, or execution-planning problem and **direct that person into Jaspen**. They should be able to experience the product, work a real decision, and decide whether it helped without speaking to anyone.

Human sales begins later, when a user or organization has already experienced value and wants something broader: team adoption, strategic integration, an enterprise deployment, or an advisory engagement. At that point, a salesperson or the Founder is accelerating trust, scope, and organizational adoption — not proving that Jaspen works.

Four practical consequences:
- **Do not optimize outbound for meetings.** The primary CTA is to use Jaspen, not to book the Founder.
- **Target the decision/problem before the title.** Titles help locate likely users, but the strongest reason to reach out is evidence that the person or company is dealing with a decision Jaspen can help structure.
- **Treat self-serve as both revenue and proof.** Product-led purchases are a legitimate revenue motion, not merely a feeder for enterprise sales.
- **Treat product usage as the best expansion signal.** An upgrade, repeat use, colleague invite, or request for broader adoption means the product has already done the hardest part of the sale.

### Language guide

Lead with plain buyer language. Use the category term when the buyer asks what category we're in, or when the audience is analyst-literate (CIO, CISO, investor, procurement).

| Context | Use |
|---|---|
| Opening line, cold outreach, product-led introduction | **"An AI platform for strategic decision support"** — or, closer to the site's own voice, *"a thought partner for decisions you have to defend."* |
| Buyer asks "what is this, exactly?" | "It's a decision intelligence platform — you own the criteria, the AI judges the evidence, and code does the math." |
| CIO / CISO / procurement / investor | **"Decision intelligence platform"** — the analyst-recognized category term |
| Marketing, site, category positioning | **"Decision intelligence"** — unchanged; this is the category Jaspen is re-founding (§8) |

**Why both, rather than one:** "Decision intelligence" is a real analyst category, and that cuts both ways. To a CIO or an investor it signals a known space and does useful work. To a transformation lead with fourteen initiatives and a January board meeting, it is a category label for a problem they experience as *"I cannot defend this prioritization"* — they do not shop by category. It also carries first-generation baggage: analysts named the space for data-science tooling, which is precisely the lineage §8 works to distinguish Jaspen from, so leading with it can invite the wrong mental model before we have framed the difference. The site already resolves this correctly — headline "Decision intelligence starts here," immediately followed by the plain-language subhead about a thought partner. **Recommendation: keep the term, demote it from the opening sentence.** Say what it does first; name the category second.

---

## 1. What Jaspen Is

Jaspen turns messy, ambiguous business context into a structured decision a leader can explain, defend, and execute.

A leader brings the situation as it actually exists — notes, emails, a board deck, competing initiatives, partial data, stakeholder opinions. Jaspen interviews them, proposes criteria, and produces a **decision artifact**: the decision statement, the options, user-owned criteria and weights, graded evidence, labeled assumptions, a confidence-calibrated score, the trade-offs, a recommendation, and a phased execution plan.

Four mechanics define the product and belong in every serious conversation:

| Mechanic | What it means | Why a buyer cares |
|---|---|---|
| **User-owned rubric** | Jaspen proposes criteria; the customer sets and re-weights them | Priorities stay leadership's, not the model's |
| **Evidence grading** | Every input is graded strong / inferred / limited / assumed | Separates what's known from what's hoped |
| **Confidence calibration** | Thin evidence mechanically caps how much a judgment can contribute | Enthusiasm cannot outrun evidence |
| **Deterministic scoring** | Models judge; **code calculates** | Same inputs, same result — the number is auditable, not generated |

The workflow is branded the **FLOW Method™** (Frame, Limits, Opportunities, Weigh). Connectors: Jira, Smartsheets, Salesforce, Snowflake, NetSuite. Three models (Pluto, Orbit, Titan) are available on every plan.

**Maturity line — hold it.** *Shipping today:* decision analysis, scorecards, evidence grading, confidence calibration, user-owned rubrics, transparent reasoning, execution planning, **Decision Confidence and Assumption Exposure**, and **canonical Decision Records** (recorded decisions, appended outcomes, lessons learned, supersession history, permission-aware retrieval into a later decision). *In development:* custody architecture beyond the private, organization-owned default. *Vision only:* Decision Library, pattern discovery, cross-record organizational learning.

Records moved from "in development" to "shipping today" in August 2026. The Library, pattern discovery, and cross-record intelligence did not, and §8.9 still applies to them. Do not over-correct.

**Two claims that must never be conflated.** Decision Confidence measures a *scored* decision: how much of its weighted criteria stand on evidence. Any readiness, completeness, or coverage figure produced *before* scoring measures how much context Jaspen has been given, which is a different question. Never present the second as the first.

**What the exposure arithmetic will and will not support.** A confidence cap only ever lowers a judgment, so obtaining evidence can only move a score up. Jaspen can say "resolving this assumption could lift Option B above Option A." It cannot say "if this assumption proves false, the plan fails." There is no downside model, and inventing one would be exactly the unfounded number the product exists to expose.

**One sentence:** General AI will tell you your plan is strong; Jaspen tells you how much of it is evidence, where you are exposed, and what would change the answer.

---

## 2. The Business Problems Jaspen Solves

The problem is not a shortage of opinions, data, or AI-generated text. It is that consequential decisions have **no architecture**. Five problems, in the language buyers use:

**1. Decisions can't be defended.**
A prioritization reaches a steering committee supported by a deck and a confident voice. When the CFO asks why *this* initiative and not *that* one, the honest answer is seniority or momentum. Jaspen makes the criteria, weights, evidence, and math inspectable, so the recommendation survives the question.

**2. Decisions can't be compared.**
Finance, Operations, Technology, and Strategy each build business cases on different criteria, producing a portfolio of incomparable submissions. Executive alignment arrives late and expensively. Jaspen applies one shared rubric across options so the comparison is real.

**3. Confidence is untethered from evidence.**
The initiative with the most polished business case wins, not the best-evidenced one. Assumed numbers and evidenced numbers look identical in a spreadsheet. Jaspen grades evidence and caps what thin support can contribute — the assumption inventory becomes visible before funding, not after.

**4. Reasoning disappears.**
The *why* lives in meetings, decks, threads, and one person's memory. When that person leaves or the cycle turns, the organization relitigates a decision it already paid to make. Jaspen preserves the reasoning as a structured artifact.

**5. Decisions don't convert into execution.**
Approval and delivery are separate universes; the trade-offs and risks surfaced during the decision never reach the plan. Jaspen derives the execution plan from the weak dimensions and risks in the scorecard — the scorecard restated as work.

Jaspen sits in the gap between the conversation (chat tools), the data (BI/analytics), and the work (Jira, Smartsheets, PPM). Those systems capture activity. None captures **judgment** in a structure that can be inspected, compared, or reused.

---

## 3. The Decisions and Workflows Jaspen Is Built For

**The shape of a good Jaspen decision:** deliberate, human-owned, consequential, cross-functional, made under incomplete evidence, and subject to someone asking why afterward. Frequency is low; stakes are high; accountability is personal.

### Best-fit decision types

| Decision type | The recurring question | Who owns it |
|---|---|---|
| **Enterprise prioritization** | Which of these competing initiatives do we approve, and in what order? | Transformation office, strategic PMO |
| **Annual / cycle planning** | Which initiatives are approved this cycle given budget and sponsorship capacity? | Executive leadership team, Strategy |
| **Capital allocation** | Where do capital, leadership attention, and organizational capacity create the most value? | CFO, investment committee, board |
| **Portfolio re-sequencing under constraint** | Budget was cut — what continues, what's reduced, what's paused, what's killed? | COO, portfolio/capital planning |
| **Transformation sequencing** | Which enterprise initiatives start this year and in what order, given 75%-committed delivery teams? | Chief Transformation Officer |
| **Growth / investment choices** | Which growth opportunities receive investment over the next 18 months? | CEO, Strategy, Corp Dev |
| **Build / buy / partner** | Which path, on what evidence, at what confidence? | CIO, BU leader |
| **Post-merger integration priorities** | What gets integrated first, and what do we protect? | Integration lead, COO |
| **Vendor and platform selection** | Defensible selection with a documented rationale for audit or board review | Procurement, CIO |

### Workflows Jaspen fits inside

- **The annual/quarterly planning cycle** — the highest-value recurring workflow. Every submitted initiative scored on the same rubric before the committee meets.
- **Stage-gate and investment-committee review** — the decision arrives with evidence grades and an assumption list attached, not just a business case.
- **Steering-committee and board preparation** — defensible prioritization with the reasoning documented.
- **Transformation-office intake and sequencing** — a repeatable decision language across a portfolio.
- **Business-case challenge** — pressure-testing assumptions, evidence, risks, and trade-offs before funding.
- **Post-decision handoff to delivery** — decision → execution plan → Jira/Smartsheets.

### Poor-fit decisions

High-volume algorithmic decisioning (pricing engines, credit decisions, ad bidding, supply-chain optimization), real-time operational calls, and anything where the buyer wants the system to decide autonomously. That is first-generation, data-science decision intelligence. Jaspen governs deliberate human judgment.

---

## 4. Product-Led User Fit and Enterprise Fit

Jaspen has **two different fit questions**, and they should not be confused.

### 4.1 Product-led user fit

For self-serve acquisition, the primary unit of targeting is the **person with the decision**, not the company profile. A strong product-led user is someone who:

- Has a consequential decision, prioritization, trade-off, investment choice, resource-allocation question, or execution-planning challenge.
- Owns or materially influences the recommendation and expects to explain *why* afterward.
- Is working with incomplete or mixed-quality evidence and would benefit from separating what is known from what is assumed.
- Has two or more plausible options and meaningful criteria that compete with each other.
- Can experience value without implementation services, procurement, or a discovery call.

Strong product-led users can appear across Strategy, Operations, Finance, Product, Technology, Marketing, Transformation, PMO, consulting/advisory, or founder/GM roles. **Decision shape matters more than title.** Company size is not a hard gate for self-serve.

### 4.2 Organizational characteristics of strong enterprise/advisory fit

*Narrative version for enterprise qualification. The scoreable version is §12-B (Company Fit).*

**Structural (the ones that matter most):**
- Decisions are **cross-functional** — no single leader can approve alone. Multiple functions submit competing asks.
- A **recurring forcing event** exists: an annual or quarterly planning cycle, a stage gate, an investment committee, a board or PE reporting rhythm.
- A **named governance body** demands justification (steering committee, investment committee, transformation board).
- **Constrained capacity** is explicit — a fixed budget, a cap on how many initiatives leadership can sponsor at once, delivery teams already near full commitment.
- **Decision-to-outcome lag is long** enough that reasoning is forgotten before results arrive.
- Enough scale for decisions to be cross-functional, but **not enough governance maturity** to have a standardized decision rubric. This mid-market-to-lower-enterprise squeeze is the enterprise sweet spot.

**Firmographic:**
- ~200–20,000 employees; multi-function, multi-site, or multi-business-unit.
- Enterprise/advisory decision financial impact typically **$1M+** per decision; value rises sharply as consequence and organizational reach increase.
- Sectors where "show your work" is standing practice: regulated industries, financial services, healthcare, public sector, PE-backed companies.

**Cultural:**
- Leadership that wants to be challenged rather than validated — the site's own promise is a partner that "won't just tell you what you want to hear."
- A tolerance for making priorities explicit. Organizations where weights are politically unspeakable will resist the product itself.

---

## 5. Outcomes a Buyer Should Expect

Tiered by what we can actually stand behind. **Only Tier A may be stated as a Jaspen result.**

### Tier A — Mechanically true, demonstrable in-product today

- **Greater consistency.** One shared rubric across every option and every submitting function. Scoring is deterministic — same inputs, same result — so the number does not drift between runs, analysts, or meetings.
- **Clearer trade-offs.** Options are compared on named criteria with explicit weights, and each score decomposes into criterion → weight → evidence grade → confidence. "Why is this a 72?" has a complete answer.
- **Stronger documentation of reasoning.** The decision artifact records the decision statement, options, criteria, weights, evidence and its quality, labeled assumptions, confidence, recommendation, and execution plan. The audit trail exists by construction, not as a follow-up task.
- **Faster alignment.** A structured, defensible recommendation in minutes rather than a cycle of workshops, spreadsheet-building, and deck iteration. Disagreement relocates from "whose analysis do we trust" to "do we agree on these weights" — a resolvable argument.
- **Visible evidence quality.** The split between evidenced and assumed inputs is explicit before funding, and "what would raise the score?" has a concrete answer.
- **A decision that converts to work.** The execution plan is derived from the weak dimensions and risks, not from a template.

### Tier B — Buyer-instrumented; co-define in a pilot, measure with the customer

Propose these as pilot success metrics; never assert them as our results:
- Cycle time from decision raised → decision approved, on a named class of decisions.
- Share of a planning cycle's initiatives scored on one shared rubric (alignment coverage).
- Reduction in re-opened or relitigated decisions per quarter.
- Share of funded initiatives whose business case rests on evidenced vs. assumed inputs.
- Time for a new leader to understand why the current portfolio looks the way it does.

### Tier C — Industry benchmarks; cite as *problem context*, always attributed

- **88%** of transformations fail to meet original ambitions (Bain); McKinsey's persistent ~30% success rate.
- **91.5%** of large projects exceed budget, schedule, or both; **43%** exceed original budget (PMI).
- **Only 1 in 5** organizations report high benefits-realization maturity.
- **~42%** of an employee's institutional knowledge is unique to them and leaves with them (Panopto, n=1,001). Gartner puts enterprise knowledge at **70–80% tacit** *(secondary citation — verify before public use)*.
- Knowledge workers lose **~8.2 hrs/week** searching for, recreating, and duplicating information (APQC, n=982).

**We have no customer outcome data yet.** Until a reference engagement closes, do not imply ROI multiples, percentage improvements, or named results.

---

## 6. Contact ICP — Users, Champions, Sponsors, and Buyers

The contact strategy has two layers.

### Product-led user layer

The broadest acquisition audience is **the person who has a consequential decision to make or defend**. Likely titles include Founder, Chief of Staff, VP/Director Strategy, Business Operations leader, Product leader, Finance/FP&A leader, Transformation lead, Portfolio/PMO leader, Business Unit leader, consultant/advisor, and functional leaders making investment or prioritization choices.

The role is a clue, not the qualification. The stronger question is: **what evidence suggests this person is dealing with a decision Jaspen can help structure right now?**

For this layer, the desired action is **use Jaspen**, not schedule a meeting. The free experience, product entry point, or a relevant decision use case should do the demonstration.

### Enterprise/advisory layer

Once usage or organizational interest appears, the site's executive-partnership intake shortlist remains useful: **CEO, Founder, COO, CFO, CIO, Business Unit Leader, PMO, Strategy Team.**

| Role | Function in the deal | What they care about |
|---|---|---|
| **Chief Transformation Officer / Chief Strategy Officer** | **Primary sponsor and economic buyer.** Highest-value enterprise beachhead. | A board-visible portfolio, personally career-relevant, measured against failure statistics everyone in the room already knows |
| **COO** | Sponsor or economic buyer | Sequencing against real delivery capacity; initiatives that don't collide |
| **CFO / FP&A** | Economic buyer when framed as capital allocation; otherwise a decisive influencer | Defensible allocation; the evidenced-vs-assumed split in every business case |
| **CEO / Founder** | Sponsor in mid-market; approves advisory engagements | Faster leadership alignment; fewer scattered bets |
| **Head of PMO / Strategic PMO** | Common champion for enterprise expansion. Runs the intake and the cycle. | A repeatable prioritization method that survives contact with politics |
| **VP/Director Strategy, Transformation Lead, Initiative Owner** | Champion and daily user. Has to *defend* the recommendation. | Not being the person who can't explain the number |
| **Head of Data / Analytics** | Technical influencer | That the score is deterministic code, not model output |
| **CIO / CISO / Legal / Procurement** | Gatekeeper, rarely a champion | Data custody, where records live, model routing, vendor risk |
| **Consulting partner / advisory firm** | User, channel, or influencer | Whether Jaspen equips their work and creates a repeatable client decision artifact |

**Enterprise beachhead:** the transformation/strategy office remains a strong organizational entry point because it has recurring decision volume, governance pressure, and budget. But it is **not the only top-of-funnel audience** for product-led acquisition.

**Expansion pattern to expect:** a user experiences Jaspen on a real decision, then brings the resulting artifact or workflow into a broader organizational conversation. The economic buyer (CTrO/CSO/CFO/COO/CEO) enters when there is a reason to discuss team adoption, enterprise scope, or advisory. The product creates the proof before the human sales motion begins.

### 6.1 Champion

**Typical titles:** Head of PMO, Director/VP Strategic PMO, Transformation Lead, Director of Strategy, Portfolio Manager, Initiative Owner, Head of Strategic Planning, Chief of Staff.

**Responsibilities:** Runs the intake and scoring of competing initiatives. Assembles the portfolio view. Prepares the recommendation the executive team approves. Owns the planning-cycle calendar. Frequently accountable for outcomes they did not have authority to choose.

**Pain points:** Has to defend a prioritization they assembled from incomparable business cases. Every function submits on different criteria. The best-written case wins rather than the best-evidenced one. Rework when leadership reopens a settled decision. Personally exposed when an initiative fails — the post-mortem lands on their method.

**Buying motivations:** Not being the person who cannot explain the number. A repeatable method that survives contact with politics. Speed through a planning cycle. Professional credibility with the executive team.

**Common objections:** "Is this another framework I have to roll out?" · "I already have a scoring spreadsheet." · "I don't control budget."

**Discovery questions:**
- Walk me through how initiatives get prioritized today — who submits, and on what criteria?
- What happens when two functions submit business cases you can't compare?
- When leadership asks why one initiative ranked above another, what do you show them?
- What's the next decision you have to defend, and when?
- How much of the current portfolio's business case rests on numbers someone assumed rather than evidenced?

**Strong-champion indicators:** Names a specific dated decision unprompted. Has been personally challenged in a governance meeting and lacked a defensible basis. Asks *how the score is calculated*. Already experimenting with AI tools on their own. Signed up self-serve before talking to us. Volunteers to bring the artifact to their executive team. Has a calendar-driven deadline they cannot move.

### 6.2 Economic Buyer

**Typical titles:** Chief Transformation Officer, Chief Strategy Officer, COO, CFO; in mid-market, CEO or Founder; occasionally a Business Unit Leader with P&L authority.

**Responsibilities:** Owns the portfolio, the budget, and the outcome. Signs the annual agreement or the advisory engagement. Answers to the board, the CEO, or the PE sponsor for allocation quality.

**Pain points:** Approving a portfolio they cannot fully defend. Late executive alignment that burns weeks of cycle time. Initiatives that fail for reasons visible in hindsight but invisible at approval. Capital committed to the loudest case rather than the strongest.

**Buying motivations:** Defensible allocation. Faster leadership alignment. Being able to answer the board's "why this, why now, why not that." Reducing the personal and reputational exposure of a portfolio that underperforms.

**Common objections:** "How do we justify the cost?" · "We already have ChatGPT." · "Are you going to be around in three years?" · "Will my team actually use this?"

**Discovery questions:**
- What decision is in front of you right now that you'd want to be more confident about?
- What's the financial impact of getting the sequencing wrong this cycle?
- When the board asks why this portfolio, what does your answer rest on today?
- How long does it currently take to get your leadership team aligned on priorities?
- Who would you want in the room for a working session on this decision?

**Notes:** Anchor to the decision, not the tool (§11). Against a $1M–$25M decision the arithmetic is not close. This is the buyer for the advisory engagements (§7).

### 6.3 Executive Sponsor

**Typical titles:** CEO, COO, Chief Transformation Officer, Board member, PE operating partner. Frequently the same person as the economic buyer in mid-market; distinct in enterprise.

**Responsibilities:** Provides political cover for a new decision method. Mandates adoption across functions. Sets whether the planning cycle actually runs on a shared rubric or reverts to decks.

**Pain points:** Functions that don't align. Decisions relitigated at their level that should have resolved below it. No institutional memory of why the last cycle went the way it did. Reliance on a small number of experienced people whose judgment cannot be inspected or transferred.

**Buying motivations:** Organizational consistency. A decision language the whole leadership team shares. Reduced dependence on individual tenure and memory. Governance that satisfies the board without adding bureaucracy.

**Common objections:** "This feels like it adds process." · "My leaders should be able to do this already." · "Let's revisit after planning."

**Discovery questions:**
- How consistent are the criteria your functions use to justify investment?
- What decisions keep coming back to you that should have been settled a level down?
- Six months after a major decision, can your team reconstruct why it was made?
- What would change if every initiative arrived scored the same way?

**Strong-sponsor indicators:** Newly in seat and rebuilding how the function decides. Has publicly committed to a transformation agenda. Under PE or board scrutiny on allocation discipline.

### 6.4 Technical Buyer

**Typical titles:** Head of Data, Director of Analytics, VP Engineering, Enterprise Architect, CIO in smaller organizations.

**Responsibilities:** Evaluates whether the mechanism is sound and whether it integrates. Assesses model routing, data flow, and connector fit (Jira, Smartsheets, Salesforce, Snowflake, NetSuite).

**Pain points:** Business teams adopting AI tools that produce unreproducible numbers. Being asked to stand behind analysis they cannot audit. Shadow AI proliferating without governance.

**Buying motivations:** Deterministic, reproducible scoring. An auditable trail. Clean integration rather than another disconnected tool.

**Common objections:** "How do I know the AI isn't hallucinating the score?" · "Which models, and where does inference run?" · "Can we export the data?"

**Discovery questions:**
- What's your current position on AI tools producing numbers that inform funding decisions?
- What would you need to see to be comfortable standing behind a score from this?
- Which systems hold the evidence today — Snowflake, Salesforce, Jira?

**Notes:** This role converts fast once **models judge; code calculates** lands. Frequently flips from skeptic to advocate in a single conversation — the strongest objection-to-advocate conversion we have. Treat as a second champion, not a hurdle.

### 6.5 Influencer

**Typical titles:** FP&A Director, Finance Business Partner, Business Unit Leader, Initiative Owner, Chief of Staff, external consulting partner.

**Responsibilities:** Builds or challenges the business cases. Advocates for their function's initiatives. Shapes what leadership sees before it reaches the room.

**Pain points:** Watching a well-evidenced case lose to a well-presented one. No consistent basis for challenging another function's numbers. Repeatedly rebuilding the same analysis each cycle.

**Buying motivations:** A level playing field for their initiatives. A defensible basis to challenge weak cases. Less rebuilding.

**Common objections:** "This is just a weighted scoring spreadsheet." · "Our consultants already do this."

**Discovery questions:**
- When you disagree with another function's business case, what can you actually point to?
- How much of your cycle is spent rebuilding analysis you've done before?
- Who currently decides which criteria matter?

**Notes:** Finance influencers can escalate into economic buyers when the framing shifts from prioritization to capital allocation. Consulting partners are a genuine channel — firms can run client engagements on Jaspen (§8).

### 6.6 Blocker

**Typical titles:** CISO, Legal Counsel, Procurement Lead, CIO (in gatekeeper posture), Data Privacy Officer. Also the informal blocker: the incumbent consulting partner or the owner of the existing PPM tool.

**Responsibilities:** Vendor risk, data custody, contract terms, security review. Or, informally, defending the territory this touches.

**Pain points:** Unvetted AI tools handling strategic and financial data. Early-stage vendors without established security posture. Loss of scope or relevance (informal blockers).

**Buying motivations:** Rarely motivated to buy — motivated to avoid risk. Reachable through custody clarity, not enthusiasm.

**Common objections:** "Where does our data live? Who can see our decisions?" · "What's your security posture as an early-stage company?" · "We already have a tool for this." · "Our firm handles prioritization."

**Discovery questions:**
- What does your review process require before a tool like this touches strategic planning data?
- Who needs to sign off, and what do they need to see?
- Is there an existing tool or partner whose scope this overlaps?

**Handling:** Lead with private-by-default records, customer ownership, custody rings, and exportability (§11). Route detailed security and DPA questions to the founder. For informal blockers, position as complementary — PPM tracks approved work, Jaspen governs the approval; consultants bring a framework and take it with them, Jaspen leaves the method behind. Surface these people early; they are far more expensive discovered at contract stage.

---

## 7. Product-Led Revenue vs. Enterprise / Advisory — Where the Value Sits

There are distinct motions. **Confusing product-led acquisition with enterprise selling is the most expensive mistake available.**

### Product-led experience and self-serve revenue

Jaspen should be discoverable and useful without a founder conversation. The free experience is the lowest-friction proof point: a person can bring a real problem, experience the decision workflow, and decide whether the product helped.

The current individual paid offer is **$999 one-time**. It is a real revenue motion, not merely a lead magnet. The purpose of outbound at this level is to put Jaspen in front of people who are likely to have an appropriate decision and let the product do the selling.

**Primary product-led conversion path:** relevant signal → visit Jaspen → use the product → see value → purchase / return / expand usage.

Track product-led success using **site visits, product activations, repeat usage, paid conversion, and revenue**. Booked meetings are not a primary KPI for this motion.

### Team / organization expansion

When multiple people want to use the same decision logic, share artifacts, establish a common rubric, or integrate Jaspen into a recurring planning/governance workflow, the value shifts from personal decision support to **organizational consistency, comparability, and reasoning that survives handoff**.

Do not force this conversation before the organization has a reason to have it. Product usage, colleague invitations, repeat decisions, security/integration questions, or requests for shared deployment are the signals that an expansion conversation may be warranted.

**Pricing note:** use the current live Jaspen offer for any team or enterprise scope. Do not reuse retired legacy monthly plan prices from earlier versions of this brief.

### Advisory engagements — high-value expansion after demonstrated fit

| Engagement | Price | What it is | When to propose |
|---|---|---|---|
| **Executive Decision Intensive** | $25,000 | One 90-minute virtual session facilitated by the Founder or a designated Customer Success Partner; tailored preparation guidance beforehand; executive-ready artifacts generated through Jaspen. For an executive or leadership team working through **one consequential strategic decision**. | A single named, dated, high-impact decision where the buyer already understands Jaspen's value and wants facilitated challenge |
| **Strategic Advisor Partnership** | $100,000 | Five 90-minute Executive Decision Intensives; preparation guidance before each; assumption, evidence, risk, and trade-off challenge; executive-ready artifacts. For organizations evaluating **multiple high-value decisions**, seeking clarity on where leadership attention, capital, and capacity create the greatest estimated financial impact. | A portfolio, a planning cycle, or a transformation agenda where broader strategic support is desired |

The mechanic in both: **the client executes in Jaspen while the advisor guides the work.** This is not consulting delivered *to* the client — it is the client's team building the decision, with challenge. The product remains central; the human adds judgment, facilitation, and strategic integration.

Per the site: **engagements are accepted based on fit, capacity, and decision readiness.** Selectivity is real and protects delivery capacity.

Qualification bands from the executive-partnership intake remain useful for advisory opportunities: financial impact of the decision (<$250K / $250K–$1M / $1M–$5M / $5M–$25M / $25M+); decision timing (within 30 days / 1–3 months / 3–6 months / more than 6 months); who participates; whether the contact is the primary decision-maker, shares the decision, or influences it.

---

## 8. Differentiation

### Against the alternatives buyers actually use

**vs. spreadsheets and ad hoc scoring models (RICE, ICE, value/effort matrices).**
A weighted spreadsheet can't grade evidence quality, so an assumed number and an evidenced number carry identical weight. It can't cap confidence. It can't interview you into the criterion you missed. It doesn't survive the analyst who built it leaving, and every function builds a different one — which is precisely why the portfolio isn't comparable. Jaspen's differentiating mechanic is the one spreadsheets structurally lack: **score contribution tied to evidence strength.**

**vs. slide decks.**
A deck is a persuasion artifact. It records the conclusion and the argument for it, never the criteria that were weighed, the evidence that was thin, or the assumptions that were made. Six months later it cannot answer why. Jaspen's artifact is built to be interrogated, not presented — and the reasoning is preserved, not the pitch.

**vs. consultants and advisory firms.**
Consultants bring the framework and take it with them; the organization rents judgment without acquiring the method. Jaspen leaves the reasoning behind, in the customer's hands, and the rubric is theirs afterward. Note the honest nuance: Jaspen *also* sells advisory (§7) — but the engagement is explicitly the client executing in Jaspen while an advisor guides, so capability transfers. Consultancies are also a **channel**: firms can run client engagements on Jaspen.

**vs. PPM and project-management tools (Jira, Smartsheets, Planview-class).**
They track work that has already been approved. Jaspen governs the approval, then hands off. Complementary, not competitive — connectors exist for exactly this reason.

**vs. generic AI (ChatGPT, Copilot, Gemini).**
The architectural difference, in order of how often it wins the conversation:
1. **Models judge; code calculates.** Every published number is deterministic and reproducible. General assistants produce the answer, the score, and the justification in a single pass — and the score can change on the next run.
2. **Confidence is mechanical, not rhetorical.** Evidence grades cap contribution. Generic AI expresses uncertainty in prose; Jaspen puts it in the math.
3. **The rubric belongs to the customer.** Chat tools silently infer what matters from the prompt. Jaspen proposes and never secretly chooses priorities.
4. **Every score decomposes.** Explainability by construction, not a rationalization generated afterward.
5. **The output is an artifact, not a message** that disappears into chat history.

### The durable differentiators

6. **Decision → execution in one flow**, derived from the weak dimensions rather than a template.
7. **The form scales, not the domain.** The same unchanged mechanism scores a personal job offer and a board's capital allocation — which is why one product serves an individual on Essential and an enterprise transformation office.
8. **Constitutional architecture.** A written Constitution governing what the system may and may not do. Lands unusually well with CIO/CISO/Legal.
9. **The compounding asset — sell as direction, never as available.** Decision Records are becoming durable, customer-owned organizational memory. The long-term moat is accumulated records and outcome history, which cannot be synthesized and accrues only at the speed of reality.

**Category framing:** analysts named "Decision Intelligence" years ago; the first generation built it as data-science tooling, where intelligence lived in models and dashboards and human criteria were never first-class objects anyone could inspect or own. Jaspen re-founds the category around **governability**: judgment explicit, math deterministic, records owned, learning transparent.

---

## 9. Buying and Acquisition Signals

Signals serve two different purposes: **deciding who should see Jaspen now** and **deciding when a human enterprise/advisory conversation is warranted**.

### Product-led acquisition signals — put Jaspen in their path

These do not require a confirmed discovery conversation. They are observable reasons to believe someone may be dealing with a Jaspen-shaped decision:

**Strong:**
- Publicly discussing a consequential strategic choice, prioritization, investment, market choice, resource-allocation problem, transformation, or competing options.
- Budget reduction, restructuring, M&A, integration, or portfolio re-sequencing that creates explicit trade-offs.
- A new senior leader taking responsibility for Strategy, Transformation, Operations, Finance, Product, or a Business Unit and setting priorities.
- A planning, investment-committee, board, stage-gate, or annual operating cycle beginning now.
- Public evidence of initiative overload, capacity constraints, misaligned priorities, or repeated decision rework.
- A consultant/advisor working with clients on strategy, transformation, prioritization, business cases, or operating-model choices.

**Moderate:**
- Job postings for transformation, strategic PMO, portfolio governance, strategic planning, FP&A, or business operations roles.
- New PE ownership or a fresh value-creation plan.
- New product/market launches or major investment announcements that imply competing allocation choices.
- Relevant engagement with Jaspen content, diagnostics, utilities, or the website.

**Product-led CTA:** introduce the relevant Jaspen use case and direct the person to the product. Do not default to a founder meeting.

### Enterprise/advisory expansion signals — human follow-up may be warranted

- A self-serve user upgrades, returns repeatedly, invites colleagues, or asks about broader use.
- A specific, dated, consequential decision is named and the user wants facilitated support.
- Unprompted questions about security, procurement, data custody, integrations, shared workspaces, or enterprise deployment.
- A leadership team wants to standardize how decisions are evaluated across functions.
- Executive-partnership intake is submitted with meaningful impact, near-term timing, and appropriate decision ownership.

**Negative signals for enterprise/advisory:** API-only access requested with no decision use case; credit pricing compared only to LLM token pricing; a request to tune the model toward a predetermined conclusion; no organizational reason to expand beyond self-serve.

---

## 10. Weak Fit and Routing Rules

Some users are weak fit for Jaspen entirely; others are simply **self-serve rather than enterprise**.

### Weak fit for Jaspen itself
- **People who want the AI to decide for them.** Jaspen makes judgment explicit and keeps accountability human.
- **High-volume algorithmic decisions** — pricing, credit, bidding, routing, supply-chain optimization. Wrong category.
- **"Cheaper ChatGPT" shoppers** whose only criterion is generic generation cost.
- **Requests to force a predetermined conclusion.** That conflicts with the product's purpose.
- **Data-poor users expecting Jaspen to supply external market data.** Jaspen works honestly with incomplete evidence, but it does not source the missing evidence for them.

### Appropriate for self-serve, but not an enterprise sales motion
- Small companies or individual leaders with real consequential decisions but no cross-functional governance layer.
- Decisions below enterprise/advisory impact thresholds that can still benefit from structured reasoning.
- One-off decisions without a recurring organizational workflow.
- Users who want the product but have no current need for shared deployment, security review, integration, or facilitated advisory.

**Routing rule:** do not disqualify a legitimate self-serve user merely because the account would be weak for enterprise. Let Jaspen serve the decision. Reserve human sales capacity for expansion opportunities where broader organizational value is evident.

---

## 11. Objections and Responses

**"We already have ChatGPT / Copilot."** Those are general assistants optimized for fluent answers. Jaspen is optimized for decisions you can defend: your rubric, graded evidence, confidence caps, and deterministic math — so the number reproduces and decomposes. The test is the moment after: when the CFO asks why it was a 72, "the AI sounded confident" is not an answer.

**"How do I know the AI isn't hallucinating the score?"** It isn't producing the score. Models judge evidence against criteria; **code calculates** every published number — weights, caps, rollups, tiers. We don't claim hallucination is impossible; we claim the architecture is built to resist unsupported conclusions, and every point is inspectable.

**"This is just a weighted scoring spreadsheet."** See §8. A spreadsheet cannot grade evidence quality, cap confidence on assumed inputs, or interview you into a missing criterion — and every function builds a different one.

**"Our consultants already do this."** They bring the framework and take it with them. Jaspen leaves the method in your hands. If you want facilitation, our advisory engagements are structured so your team executes in Jaspen while an advisor challenges assumptions, evidence, risk, and trade-offs — capability stays with you.

**"Where does our data live? Who can see our decisions?"** Decision Records are private and customer-owned by default. Custody rings distinguish private customer records, explicitly opted-in and anonymized library content, and governed non-identifying internal calibration. One canonical schema does not mean one shared data pool. Route detailed security/DPA questions to the founder.

**"We don't have good enough data for this."** That's the normal case and the product is designed for it. Weak evidence doesn't block progress — it lowers confidence, visibly and mechanically, with assumptions labeled. You get an honest first score today and a concrete answer to "what would raise it."

**"It's another framework to roll out."** There is no framework to roll out. It starts as a conversation — paste the situation as it exists. Structure comes out the other side, in the first session.

**"How do we justify the cost?"** Anchor to the decision, not the tool. Against a $1M–$25M decision, the arithmetic is not close. One re-sequenced initiative or one planning cycle that doesn't slip is the whole case.

**"Are you going to be around in three years?"** Acknowledge the stage directly. Records are customer-owned and exportable, the founder is personally accessible, and early customers shape the roadmap. Do not oversell headcount or traction.

---

## 12. Implications for Ideal Customer Profile

Jaspen now uses a **two-motion ICP model**:

1. **Product-Led User Fit** — who is likely to benefit from using Jaspen directly, regardless of company size or enterprise readiness?
2. **Enterprise / Advisory Fit** — when is there enough organizational structure, urgency, and scope to justify human sales or advisory attention?

Do not use enterprise criteria to artificially shrink the self-serve market.

### 12-A. Product-Led User Fit

Score or filter primarily on the **shape of the decision and observable need**.

| # | Characteristic | Strong-fit indicator | Source of evidence |
|---|---|---|---|
| P1 | **Consequential decision likely** | Strategic choice, prioritization, investment, resource allocation, market choice, vendor/platform choice, or execution-plan decision | Public statements, role context, posts, company news |
| P2 | **Human judgment required** | Multiple plausible options; no simple algorithmic answer | Role / use case |
| P3 | **Accountability / defensibility** | Person owns or materially influences a recommendation someone may challenge | Title, governance context, public role |
| P4 | **Incomplete or mixed evidence** | Decision requires assumptions, judgment, or reconciliation of conflicting inputs | Public context, use-case inference |
| P5 | **Trade-offs are real** | Criteria compete; choosing one path sacrifices something else | Event / initiative context |
| P6 | **Near-term reason to act** | Planning cycle, budget change, new role, launch, transformation, M&A, investment, or other forcing event | News, job changes, fiscal calendar, hiring |
| P7 | **Product can prove value directly** | User can bring the problem into Jaspen without requiring consulting or implementation first | Use-case assessment |
| P8 | **Repeat-use potential** | Role regularly makes or facilitates consequential decisions | Role / function |

**Targeting guidance:** title is a locator, not a gate. Prefer people with evidence of P1–P6 over people who merely hold an ideal title.

**Primary outcome:** product visit → activation → repeat use / paid conversion. Meeting booked is not a success metric for this motion.

### 12-B. Enterprise Company Fit

Timing-independent. Scored once and revisited annually or on a major structural change. This applies to **enterprise expansion and advisory**, not to whether someone may use Jaspen self-serve.

| # | Characteristic | Strong-fit indicator | Source of evidence |
|---|---|---|---|
| A1 | **Transformation office exists** | A CTrO, transformation office, or enterprise change function in seat | LinkedIn, org announcements, careers page |
| A2 | **Strategic PMO or portfolio function exists** | A PMO that runs intake and prioritization, not just delivery tracking | LinkedIn titles, job postings |
| A3 | **Enterprise governance body** | Steering committee, investment committee, transformation board, stage gates, or PE sponsor reporting | Annual report, investor materials, discovery |
| A4 | **Annual/quarterly planning cadence** | A real, calendared cycle where initiatives are submitted, compared, and approved | Discovery; fiscal calendar |
| A5 | **Cross-functional decision making** | 3+ functions submit competing asks; no single approver can decide alone | Discovery; org structure |
| A6 | **Executive sponsorship available** | A named CTrO, CSO, COO, CFO, CEO, CIO, BU Leader, PMO, or Strategy Team lead | LinkedIn, leadership page |
| A7 | **Decision complexity** | Multi-criteria, multi-stakeholder, incomplete evidence, long outcome lag | Discovery |
| A8 | **Typical decision financial impact** | $1M+ per decision; $5M–$25M+ ideal for advisory | Discovery, budget disclosures |
| A9 | **Company size** | ~200–20,000 employees; multi-function, multi-site, or multi-BU | LinkedIn, firmographic data |
| A10 | **Revenue band** *(inference — calibrate against real deals; not yet validated)* | Roughly $50M–$5B | Public filings, firmographic data |
| A11 | **Governance-maturity gap** | Enough scale for cross-functional decisions, but no standardized decision rubric | Discovery |
| A12 | **Constrained portfolio structure** | Fixed investment budget, cap on concurrent initiatives, delivery teams near full commitment | Discovery, planning artifacts |
| A13 | **Documentation / auditability pressure** | Regulated sector, board reporting, or PE value-creation-plan scrutiny | Sector, ownership structure |
| A14 | **AI maturity — the middle band** | AI comfort exists, but leadership has hit the ceiling of what a general assistant can defend | Tech-stack data, job postings, public AI statements |
| A15 | **Decision type is deliberate, not algorithmic** | Human-owned, low-frequency, high-stakes. **Hard disqualifier when it fails** | Sector, discovery |

**Weighting guidance (to validate):** A1–A5 are the structural core. A15 is a gate. A10 remains the weakest-evidenced criterion and should be recalibrated against real customers.

### 12-C. Enterprise Purchase Readiness

Event-driven and perishable. Re-score continuously.

| # | Signal | High-readiness indicator | Decay | Points | Half-life |
|---|---|---|---|---:|---:|
| R1 | **Existing Jaspen usage** | User has activated, returned, purchased, upgraded, or invited colleagues | Slow — persists and compounds | 15 | 365d |
| R2 | **Named strategic decision underway** | A specific, dated, consequential decision the prospect can articulate | Fast | 25 | 45d |
| R3 | **Budget or planning cycle within 90 days** | Annual/quarterly cycle, stage gate, or investment committee inside the window | Predictable | 12 | 90d |
| R4 | **New CTrO / CSO / COO or comparable leader in seat** | First 90–180 days, rebuilding priorities or decision process | Medium | 10 | 180d |
| R5 | **M&A, restructuring, or integration** | Announced or in progress; priorities unresolved | Medium | 8 | 180d |
| R6 | **Cost reduction / budget cut** | Portfolio must be re-sequenced under a hard new constraint | Fast | 8 | 45d |
| R7 | **Acute capacity constraints** | Leadership cannot sponsor more initiatives; something must be cut | Medium | 7 | 180d |
| R8 | **Board or PE pressure event** | New ownership, fresh value-creation plan, or allocation discipline under scrutiny | Medium | 8 | 180d |
| R9 | **Expansion behavior** | Security, custody, procurement, integrations, shared deployment, or organizational adoption questions | Fast | 7 | 21d |
| R10 | **Advisory intent** | Executive-partnership intake, request for facilitated decision support, or broader strategic partnership | Fast | 8 | 21d |

**Important:** a named decision is **not a gate for product-led outreach**. It becomes especially important when deciding whether to spend human sales/advisory capacity. Existing product usage is the strongest evidence that a human expansion conversation may be productive.

**How this is implemented (`jaspen-rubric-v3.1`).** Points and half-lives above are the deployed values. A signal contributes `points × 0.5^(days ÷ half-life) × confidence`, and the account total is capped at 100.

- **No active R2** — no named strategic decision underway — **caps Purchase Readiness at 40.** Without a nameable decision there is nurture, not pursuit.
- **Active R1** — existing Jaspen usage — **floors Purchase Readiness at 35.** Usage alone justifies working an account.
- The **45 enterprise-readiness threshold** is unchanged. Because the cap sits below it, a named strategic decision is what makes an enterprise-ready route reachable.
- **Evidence confidence** is carried with the evidence and multiplies signal points: High 1.00, Medium 0.70, Low 0.40. Evidence sent without a confidence value scores as Low.
- **Signal dates carry explicit precision** — `day`, `month` or `quarter` — recording what the source actually supplied. An inferred day is never presented as sourced. Month and quarter precision anchor decay to the earliest date in the period, so imprecision costs readiness rather than earning it. A readiness date must be attested by the evidence claim; `observed_at` records when evidence was observed, not when the event happened, and never validates an event date.
- **R11 is retired.** It is not a valid code and is rejected by the schema.

### 12-D. Routing Logic

**A15 is evaluated first, as a hard gate.** The engine returns `a15_deliberate_decision` as `pass`, `fail` or `unknown`, and stores the verdict on the qualification record. A `fail` — an algorithmic or high-volume decision domain — routes to `hold` regardless of Product-Led User Fit, Company Fit or Purchase Readiness; the thresholds are not evaluated. `unknown` does not gate, because absent evidence is not a failed test.

Routing then resolves in precedence order: `enterprise_ready` → `product_led_review` → `enterprise_nurture` → `hold`.

**Good product-led fit, low enterprise fit** — send to Jaspen. Let self-serve revenue happen. Do not consume enterprise sales capacity.

**High enterprise fit, low current readiness** — continue signal-based nurture. Put Jaspen in front of likely users and watch for product activity or a forcing event. Do not push a meeting merely because the company is attractive.

**High enterprise fit + high readiness** — expansion opportunity. A human salesperson can now help with organizational scope, commercial terms, integration, or advisory because the conversation is about broader value, not convincing someone to try the product.

**Low product fit** — do not pursue, regardless of company size or urgency.

**Route names as implemented.** `enterprise_ready` — Company Fit ≥ 55 and Purchase Readiness ≥ 45. `product_led_review` — Product-Led User Fit ≥ 60, evaluated independently of the enterprise thresholds. `enterprise_nurture` — Company Fit ≥ 55 with readiness below 45. `hold` — nothing qualifies, or A15 failed. Thresholds remain 60 / 55 / 45.

Because `product_led_review` is tested on its own axis, **enterprise criteria never block a legitimate product-led user**: a person with a Jaspen-shaped decision routes to review even when their company falls below 55.


### 12-E. Explicit exclusions / negative signals

Algorithmic or high-volume decision domain (hard disqualifier) · buyer seeking autonomous decisioning · request to force a predetermined conclusion · PPM-replacement intent · "cheaper ChatGPT" price shopping · API-only interest with no decision use case.

For enterprise/advisory only, also downgrade: no recurring organizational use case · no cross-functional/governance layer · no meaningful expansion need · decision impact too small to justify human delivery capacity.

