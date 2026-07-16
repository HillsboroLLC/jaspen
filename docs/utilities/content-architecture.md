# Jaspen Content Architecture — 2 to 3 Year Plan (v2)

Last updated: 2026-07-15
Status: proposed, not approved. Nothing in this document has been built.
Supersedes: v1 of this document (2026-07-15, same day) — the single "Decision Impact Assessment" concept from v1 is retired in favor of the Assessments/Utilities split below. Everything else from v1 (search intent table, linking logic, reuse matrix) carries forward, adjusted for the new structure.

## 0. What changed and why

Two shifts from the last round, both of which sharpen the plan rather than replace it:

1. **Assessments and Utilities are different tools for different moments**, not two names for "lead magnet." An Assessment teaches someone something about themselves or their organization (self-discovery, personal, DISC-like). A Utility answers a specific business question with a real number, standalone, whether or not the person ever talks to Jaspen (Website-Grader-like). Collapsing these into one "Decision Impact Assessment" in v1 was a mistake — it tried to be both and would likely have done neither convincingly.
2. **The marketing has to start from the pain the exec already feels, not from "you should have a better decision process."** Nobody searches for that. They search for (or complain about) the downstream symptom: initiatives that don't deliver, decisions that get relitigated, alignment meetings that eat the calendar, projects that burn budget before showing value, decisions nobody can explain six months later, knowledge that leaves when someone quits. The content pillars below are rebuilt around those six pains directly.

One finding worth naming up front: **two of your six stated pains — "why can't anyone explain this decision six months later" and "why does knowledge leave with employees" — are both, directly, organizational memory.** That's a strong, unprompted signal that organizational memory deserves to be a primary content pillar, not a future feature footnote. See §5.

## 1. The three categories, defined

| | Assessment | Utility | Educational content |
|---|---|---|---|
| **Answers** | "What does this reveal about me / my team / my org?" | "What does this cost me, right now, specifically?" | "How do I think about this problem well?" |
| **Feels like** | DISC, CliftonStrengths, a personality/style quiz | Website Grader, a mortgage calculator, a speed test | A guide, an article |
| **Needs an email to see full value?** | Usually yes — the result is personal enough that "send me my results" feels natural | No — the number should show immediately; email is for a saved/detailed report, not gatekeeping the answer | No — never gate real information behind an email |
| **Walk-away feeling** | "I learned something about myself." | "That was genuinely useful." | "I understand this better now." |
| **Primary funnel role** | Mid-funnel, personal, converts curiosity into an email | Top-of-funnel, shareable, converts a stranger into a known visitor with zero commitment | Top-of-funnel, SEO discovery, builds trust before either of the above |

The dividing line I used to sort your two example lists: an Assessment is about a *pattern* that exists independent of any single decision (how you or your org tend to decide). A Utility is about a *specific number tied to a specific situation* (this meeting, this project, this org's actual turnover rate). That's also why "Initiative Readiness Assessment" belongs with the Utilities despite its name — it's scoped to one specific initiative's readiness, not a general pattern about how someone decides. I'd suggest renaming it "Initiative Readiness Calculator" or "Initiative Readiness Check" to avoid confusing it with the general "Decision Readiness" self-assessment, which is a pattern-level Assessment.

## 2. Assessments — recommended set and sequence

| Assessment | Status | What it reveals | Notes |
|---|---|---|---|
| **Decision Profile** (built on today's Decision Style Assessment) | Exists | An individual's natural decision-making style, strengths, blind spots | Keep as the primary homepage entry point. No changes needed to its mechanism, only to how it's positioned relative to the new Utilities (see §4). |
| **Team Decision Style** | Future, near-term | How a team collectively decides — where members diverge, where they default to the loudest voice or the highest title | Natural extension of Decision Profile once individual results exist; could literally aggregate individual profiles for people on the same team. |
| **Decision Readiness** | Future, near-term | Whether someone (or their org) generally has what it needs — evidence, alignment, time — before committing to decisions, as a recurring pattern | General pattern, not initiative-specific — pairs with, but is distinct from, the Initiative Readiness Calculator (Utility, §3). |
| **Decision Confidence** | Future, mid-term | How much of the org's current decision-making rests on genuine evidence vs. assumption, as a general pattern | Directly mirrors Jaspen's own confidence-cap mechanism — this is the assessment most likely to make someone think "I need to see this expressed with real evidence, not my own guess," which is the cleanest possible bridge into a Jaspen conversation. |
| **Organizational Decision Maturity** | Future, longer-term flagship | Where an org sits on a maturity curve — ad hoc, inconsistent, structured, institutionalized | Highest potential (category-defining, like a CMMI or DISC for decision-making) and highest effort/risk. Build this last, once the simpler assessments have proven the mechanism and given you real response data to calibrate a maturity model honestly. |

Sequence: Decision Profile is already live. I'd build Decision Readiness next (simplest new one, clean pattern-level self-assessment), then Team Decision Style (extends the same mechanism to a second altitude), then Decision Confidence (ties most directly to the product), and treat Organizational Decision Maturity as the eventual flagship once the others have proven the format and given you enough real response patterns to build a defensible maturity model rather than a guessed one.

## 3. Utilities — recommended set and sequence

All six of your candidates are legitimate; here's how I'd rank them for build order, weighing (a) how directly the calculation maps to numbers a business person already has on hand, (b) how directly it ties to one of the six named pains, and (c) how easily it avoids promising savings it can't back up.

| Utility | Maps to pain | Why this order |
|---|---|---|
| **1. Executive Meeting Cost Calculator** | "Leadership spends too much time reaching alignment" | Build first. Inputs are things people already know (attendee count, seniority/rate, frequency, duration) — no modeling judgment calls, no risk of overclaiming, and the output (a real dollar figure for time spent) is viscerally satisfying on its own, the way a mortgage calculator is. Fastest to build, safest to publish, good proof of the Utility format before investing in harder ones. |
| **2. Cost of Your Decision Process Calculator** | "Initiatives don't deliver expected results" / general | Second — broader version of #1's mechanism (time × people × frequency, but for the decision cycle itself: how long decisions take, how many people are looped in, how often they get revisited). Reuses the same calculation pattern as #1, so it's a fast follow, not a new build from scratch. |
| **3. Initiative Readiness Calculator** (rename from "Assessment") | "Projects consume resources before producing value" | Third — scoped to one specific initiative, so it's naturally the tool someone reaches for right before committing budget, which is a strong moment to be present in. |
| **4. Organizational Knowledge Loss Calculator** | "Knowledge leaves with employees" / "can't explain past decisions" | Fourth — high strategic fit (ties directly to the elevated Organizational Memory pillar, §5), but harder to model credibly: needs defensible assumptions about turnover, ramp-up time, and repeated-work cost. Worth the extra care rather than rushing it. |
| **5. Project / Initiative Outcome Impact Calculator** | "Initiatives don't deliver expected results" | Fifth — real value, but conceptually close to #2 and #3; sequence after them so it can be genuinely differentiated rather than redundant. |
| **6. Resource Allocation Impact Calculator** | "Projects consume resources before producing value" | Last of the current list — the most abstract inputs (allocation across competing initiatives), hardest to make feel instant, and most likely to need Jaspen-side modeling maturity before it can be trustworthy as a standalone tool. |

Each utility's result screen should end the same way, per your instruction: not "buy Jaspen," but "would you like Jaspen to help you think this through?" — the calculator proves there's a real number worth caring about; Jaspen is where you do something about it.

## 4. How Assessments, Utilities, and educational content work together

A single coherent path, not three separate funnels:

1. **Educational content (pain-first)** is what search and social bring people to. It's genuinely useful on its own and never gates information. Its job is trust, and its CTA points to whichever Utility or Assessment matches the pain the piece just discussed.
2. **A Utility** is the natural next step from content, or a direct entry point on its own (utilities are inherently more shareable/linkable than an assessment — nobody feels self-conscious sharing "our meetings cost $40k a month," the way they might hesitate to share a personality-style result). Utilities require zero commitment and prove value immediately, which is exactly why they're the better top-of-funnel tool between the two categories.
3. **An Assessment** is the natural next step *after* a Utility has already established "this is a real, costly problem" — now the visitor is primed for the more personal question of "why does this keep happening to me/us," which is what an Assessment answers. This is also the more natural moment to ask for an email, since the exchange (a personal result, delivered to you) feels earned rather than transactional.
4. **The Jaspen conversation** is the destination from either path, always framed as the same continuation: "you now know there's a real cost, or a real pattern — want to work through your actual decision with a thought partner?"

So the general flow is Content → Utility → Assessment → Jaspen, though real visitors will enter at any point (a shared calculator result, a LinkedIn post, a direct search for "Jaspen Score") — the point isn't to force one path, it's to make sure whichever piece someone lands on has a clear, low-pressure next step toward the others.

## 5. Do the content pillars change?

Yes — reframed around the six named pains instead of decision-making mechanics, and organizational memory is elevated from a "future, parked" idea in v1 to a primary pillar now.

| Pillar (pain-first framing) | Underlying mechanism it teaches | Maps to pain |
|---|---|---|
| **1. Why decisions get relitigated and knowledge walks out the door** (Organizational Memory — new, elevated) | Decision Records: capturing what was decided, why, what was assumed, what was traded off | "Can't explain a decision six months later" / "knowledge leaves with employees" |
| **2. Why alignment meetings eat the calendar** (was "Framing a Decision") | Clear decision statements, defined decision rights, the right people in the room from the start | "Leadership spends too much time reaching alignment" |
| **3. Why initiatives don't deliver what was promised** (was "Building the Right Rubric") | Choosing criteria that actually predict outcomes, weighting deliberately instead of by gut | "Initiatives don't deliver expected results" |
| **4. Why the same decision keeps coming back around** (was "Pressure-Testing a Decision") | Assumption-surfacing, confidence grading, knowing when you actually have enough evidence | "We keep revisiting the same decisions" |
| **5. Why projects burn resources before showing value** (was "Decision to Execution") | Deriving the execution plan from the decision's actual weak points and risks, not a generic template | "Projects consume resources before producing value" |
| **6. Decision-making frameworks, compared** (unchanged — supporting/router content) | DACI, RAPID, weighted scoring, positioned honestly | Not pain-specific — this is the comparison-shopping / topical-authority page that routes into the other five |

Pillar 1 (Organizational Memory) is the one structural change worth sitting with: it's not just a future Decision Library. It can start now, as an educational pillar (why institutional knowledge decays, what it costs to keep re-deciding the same thing), it already has a matching Utility (#4, Knowledge Loss Calculator), and the Decision Library remains its long-term proof asset once real, permissioned customer decisions exist. All three content categories thread through one pillar — that's a good sign it's structurally sound, not just thematically nice.

## 6. Where each experience creates durable competitive advantage

Ranked by how hard it would be for a competitor to copy convincingly:

1. **Organizational Memory content + eventual Decision Library.** Hardest to copy by construction — it requires an actual accumulated base of real decisions with real outcomes. A competitor can copy an article; they cannot copy years of your customers' decision history.
2. **Decision Confidence assessment (and its supporting pillar).** Confidence-capped, evidence-graded scoring is Jaspen's real mechanism, per your own Constitution. A competitor could publish a "how confident are you" quiz, but without the underlying product actually grading and capping confidence the way Jaspen does, their version would be cosmetic. Yours would be provably real.
3. **Organizational Decision Maturity assessment**, once built with real rigor. This is the highest-ceiling asset on the whole list — a maturity model can become industry vocabulary the way CMMI or DISC did — but it's also the easiest one to build badly (a maturity model with no real calibration data behind it is just an opinion with a nice UI). Worth the wait to build it right.
4. **The Utilities as a set**, more modestly durable: individually copyable (anyone can build a meeting-cost calculator), but the fact that Jaspen has five or six of them, each mapped to a named business pain and each routing into the same underlying thought partner, is a coherent system a competitor would have to replicate wholesale, not piecemeal.

## 7. Everything carried forward from v1 (adjusted, not repeated in full)

- **Search intent, internal linking logic, and the cross-format reuse matrix** (pillar → Decision Note → blog → landing page → email → LinkedIn) from v1 still apply, now pointed at the six-pillar structure in §5 instead of the original five.
- **Publishing order** updates to: Organizational Memory pillar + Knowledge Loss Calculator first (since it's the newly-elevated, dual-purpose pillar), then Meeting Cost Calculator (fastest safe Utility win), then the Rubric pillar + Weighted Decision Matrix guide (still your strongest existing-page extension), then Decision Readiness assessment, then the remaining pillars and utilities in the order listed in §2/§3.
- The **v1 caution about not fabricating case studies** still applies fully — the Decision Library stays gated on real, permissioned customer decisions regardless of how much the rest of this architecture has changed.

## Summary: what I'd want your sign-off on

- The Assessment/Utility split and the specific sequencing in §2 and §3.
- Elevating Organizational Memory to a primary pillar (§5), not just a future feature.
- The Content → Utility → Assessment → Jaspen flow in §4 as the general (not forced) journey logic.
- Retiring the single "Decision Impact Assessment" concept from v1 in favor of the Utility family above.
