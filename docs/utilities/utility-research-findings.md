# How People Actually Talk About These Problems — Research Findings

Last updated: 2026-07-15
Status: research only. Nothing built. This informs, and in one case corrects, the Utility sequencing in `content-architecture.md` v2.

## Method

Live web research across the twelve problem areas requested, looking for real phrasing (search results, forum/community discussion, existing tools, industry surveys), not assumed keywords or invented volume estimates. Sources are cited inline. Where I found strong existing tools, I'm naming them so we don't rebuild something already commoditized.

## Findings by cluster

### Projects failing to deliver / poor ROI / initiative success

**Real language:** "why projects fail," "project failure rate," "70% of projects fail," "poor ROI," "business transformation failure." People argue about the *definition* of failure as much as the rate itself — one PM forum thread is literally titled "Is that actually true that 50% of projects fail?"

**Numbers people already cite and would recognize:** Standish Group's 65-71% project failure rate; Bain's finding that 88% of business transformations miss their original ambitions; McKinsey's 30% transformation success rate, unchanged for years. These are load-bearing, widely-cited stats — worth referencing as external validation in content, not worth re-deriving ourselves.

**What they actually want to know:** not "what's the industry failure rate" (they've seen that stat many times), but "is *my* initiative going to be one of the failures, and can I tell before I've spent the budget."

**Existing tools:** mostly static ROI-calculation guides and business-case templates (HBS, Epicflow, Flowlu) — formula explainers, not interactive calculators that take your inputs and give you a number.

**Gap:** no interactive, forward-looking "is this initiative set up to succeed" tool — only after-the-fact ROI formula guides. This is real white space.

Sources: [PMI — Why do projects really fail](https://www.pmi.org/learning/library/identify-factors-cause-project-failure-2442), [Bain — 88% of transformations fail their ambitions](https://www.bain.com/about/media-center/press-releases/2024/88-of-business-transformations-fail-to-achieve-their-original-ambitions-those-that-succeed-avoid-overloading-top-talent/), [McKinsey — successful transformations](https://www.mckinsey.com/capabilities/people-and-organizational-performance/our-insights/successful-transformations), [ProjectManagement.com discussion thread](https://www.projectmanagement.com/discussion-topic/183272/is-that-actually-true-that-50--of-projects-fail-)

### Resource waste / rework

**Real language:** "cost of rework," "rework budget," people rarely say "resource waste" on its own — they attach it to a specific thing (rework, scope creep, redoing work).

**Numbers people already cite:** rework consumes 30-50% of development time in some studies; unclear requirements alone can add 10-30% to cost; reworked code is roughly 2.5x more expensive than getting it right the first time.

**Existing tools:** a "Software Development Waste Calculator" (Planview) exists for flow-efficiency waste specifically in dev teams — worth knowing as a category precedent, but it's narrow (engineering-only) and vendor-branded.

**Gap:** a general-purpose (not engineering-specific) rework cost estimator, framed around "how much of your team's time this quarter went to redoing already-completed work" — genuinely underserved outside of software engineering specifically.

Sources: [Code Climate — rework is costing millions](https://codeclimate.com/blog/rework-costs-millions), [Capicua — reducing cost of rework](https://www.capicua.com/blog/cost-of-rework-software-development), [Planview — Software Development Waste Calculator](https://www.planview.com/lp/software-development-waste-calculator/)

### Executive decision delays / analysis paralysis / decision fatigue

**Real language:** "analysis paralysis," "decision fatigue," "cost of delay," "decision velocity." Less forum chatter than expected — this topic lives mostly in leadership-coaching and consulting content (Korn Ferry, Forbes), not community discussion. That itself is a signal: executives read about this in a curated-advice register, not a peer-to-peer one.

**What they care about:** a real, specific finding worth using directly — "the cost of delay almost always exceeds the cost of a fixable mistake," and Type 2 (reversible) decisions should be made fast with good-enough data. This is close to language Jaspen could credibly use.

**Existing tools:** none found that quantify decision delay cost — this entire space is advice articles, no calculators.

**Gap:** real, but the hardest of the group to model honestly — quantifying "cost of delay" requires assuming a $ value for the initiative and an opportunity-cost rate, both of which are genuinely speculative per-company. I'd treat this as educational content territory before it's a calculator (see recommendation #7 below).

Sources: [Forbes — slow executive decisions cost more than wrong ones](https://www.forbes.com/sites/markmurphy/2026/03/10/slow-executive-decisions-cost-more-than-wrong-ones/), [Korn Ferry — 6 ways to handle decision fatigue](https://www.kornferry.com/insights/this-week-in-leadership/6-ways-to-handle-decision-fatigue)

### Organizational alignment

**Real language:** "why is alignment so hard," "decision rights," "misalignment." A specific, quotable finding: misalignment usually isn't an indecisiveness problem, it's that "decision rights and trade-offs aren't explicit."

**Existing tools:** none found as interactive tools — this is pure thought-leadership content (Navalent, CCL).

**Gap:** alignment resists a clean formula (unlike meeting cost or rework, there's no obvious input × rate = output), so I'd treat this as educational content rather than force a calculator that wouldn't hold up.

Sources: [Navalent — hidden risks of poor organizational alignment](https://www.navalent.com/resources/blog/organizational-alignment/), [CCL — the alignment trap](https://www.ccl.org/articles/leading-effectively-articles/organizational-alignment-polycrisis/)

### Decision documentation / decision logs

**Real language:** "decision log," not "decision documentation" (that's our phrase, not theirs). A near-perfect quote for our purposes: *"a month after a decision, teams remember the outcome but not the reasoning, and three months later, someone proposes the alternative that was already rejected."*

**Existing tools:** many static decision-log **templates** (monday.com, Plane, ProjectManager.com, Elium, Rebel's Guide to PM) — this is a well-established PM content category.

**Gap, and it's a real one:** every existing "decision log" resource is a template to fill in yourself. I found zero interactive tools that assess *how much decision reasoning you've already lost* or *how exposed you are* to this problem. This is the clearest white space in the whole research set, and it maps directly onto Jaspen's actual Decision Record mechanism — not a generic template, a diagnostic.

Sources: [Monday.com — decision log guide](https://monday.com/blog/project-management/decision-log/), [Plane — decision log](https://plane.so/blog/decision-log-what-it-is-why-teams-use-it-and-template), [ProjectManager.com — decision log](https://www.projectmanager.com/blog/project-decision-log)

### Organizational knowledge loss / tribal knowledge / institutional knowledge / lessons learned

**Real language:** "tribal knowledge," "institutional knowledge," people use these near-interchangeably. Manufacturing content uses "tribal knowledge" heavily; corporate/office content leans "institutional knowledge."

**Numbers people already cite:** IDC estimates $2.5-3.5M/year lost to ineffective knowledge systems per enterprise; Fortune 500 companies lose $31.5B/year to poor knowledge sharing; 70% of critical operational knowledge is never written down; after a senior employee leaves, the remaining team's efficiency drops ~48% for months. One vivid, citable anecdote: an aerospace manufacturer spent $2.3M replacing a retiring machinist's knowledge that could have been captured for roughly $10,300.

**Existing tools:** several employee-turnover-cost calculators already exist (Bonusly, National Calculator Authority) — but every one of them calculates the cost of *replacing the person* (salary %, recruiting, ramp time). None calculates the cost of losing the *reasoning behind decisions* that person was part of, which is the distinctly Jaspen-relevant angle.

**Lessons learned specifically:** real, well-documented reason teams skip it — by the time anyone writes it up, the team has moved on, and unstructured notes don't turn into anything reusable. This is a process-friction problem, not an awareness problem — people already know lessons-learned matters, they just don't do it. That argues for a tool that produces the artifact automatically rather than content that argues they should.

**Gap:** existing calculators price the person leaving. None price the decisions and reasoning leaving. That's a specific, defensible, differentiated angle tied directly to your product's actual Decision Record mechanism.

Sources: [Medium/Topple — true cost of employee turnover: knowledge loss](https://medium.com/@topple/the-true-cost-of-employee-turnover-knowledge-loss-topple-d83516330400), [24G — the $2.3M tribal knowledge problem](https://www.24g.com/blog/tribal-knowledge-loss-prevention), [HRMorning — turnover and institutional knowledge loss](https://www.hrmorning.com/articles/turnover-institutional-knowledge-loss/), [Bonusly — cost of employee turnover](https://bonusly.com/post/cost-of-employee-turnover)

### PMO / operations leader pain points (context for who's asking)

Real, current survey data: resource management is the #1 operational challenge for PMOs; only 19% of PMO professionals feel the PMO is recognized for the value it delivers; lack of executive support and misalignment with strategic goals are named repeatedly. This is useful context for tone — PMO and ops leaders are motivated by *proving value upward*, which argues for tools that produce a shareable number they can bring to leadership, not just personal insight.

Source: [Planisware — top PMO challenges 2026](https://planisware.com/resources/project-management-office-pmo/top-pmo-challenges-2026-9-experts-share-their-insights)

## A needed correction to the v2 architecture

v2 recommended the Executive Meeting Cost Calculator as the first, safest Utility to build. Direct research changes that: **meeting cost calculators are one of the most saturated free-tool categories that exists** — I found at least ten live, free, no-signup competitors (Koalendar, MeetingCalc, meetingcostcal.com, Worklenz, HBR's own version, and more), several with real-time Zoom/Meet integrations. Building a generic one now would mean competing with well-established free tools for zero differentiation, and it wouldn't create any natural bridge to Jaspen since none of the pain is decision-specific.

**Revised recommendation:** either drop this Utility, or narrow it sharply to something none of the competitors do — cost of meetings held *specifically to reach a decision or alignment*, not general meeting cost. That reframing at least ties it to the Alignment pillar. I'd deprioritize it either way in favor of the two clearer white-space opportunities below.

## Recommended opportunities

Each includes a working title, the real search intent, the actual problem, which category it belongs to, and why someone would share or bookmark it.

### 1. Decision Memory Gap (Utility) — highest-confidence white space
- **Search intent:** "decision log," "why can't we explain this decision," people looking for a decision-log template land here instead
- **Real problem:** teams re-litigate old decisions because nobody remembers the reasoning, and no existing tool measures this — only static templates exist to fix it after the fact
- **Category:** Utility. A few inputs (major decisions per year, people typically involved, how often a past decision gets re-argued) produce an estimated number of hours/dollars spent re-deciding things already decided
- **Why share/bookmark:** it produces a number people didn't have before and immediately recognize as true — the kind of thing a PMO lead forwards to their VP with "this is why we need a better system"

### 2. Decision Log Health Check (Assessment, borderline Utility)
- **Search intent:** "decision log template," "how to document decisions"
- **Real problem:** people know they should keep a decision log (it's a well-established PM practice) and mostly don't, or do it inconsistently
- **Category:** Assessment — a short set of yes/no self-check questions ("can you find the reasoning behind your last 3 major decisions in under two minutes?") producing a documentation-gap score, a pattern about the org, not a single dollar figure
- **Why share/bookmark:** genuinely fun/uncomfortable to answer honestly, DISC-quiz-like shareability ("we scored a 3/10, yikes")

### 3. Initiative Readiness Score (Utility)
- **Search intent:** "project readiness assessment," "readiness checklist" — currently all static PDFs and checklists
- **Real problem:** teams commit budget to initiatives before checking whether resourcing, stakeholder alignment, and risk are actually in place
- **Category:** Utility, but interactive and scored rather than a checklist — that alone differentiates it from everything I found
- **Why share/bookmark:** used right before a stage-gate or budget-approval meeting; the score becomes the artifact someone brings into that meeting

### 4. Rework Cost Estimator (Utility)
- **Search intent:** "cost of rework," "rework budget"
- **Real problem:** rework is a large, well-documented cost (30-50% of dev time in some studies) but teams outside of software engineering rarely quantify it for themselves
- **Category:** Utility — inputs like team size, hours/week, estimated % of time spent redoing finished work, benchmarked against the real external stats above
- **Why share/bookmark:** produces a specific dollar figure people didn't have; useful ammunition in a budget conversation

### 5. Institutional Knowledge Risk Calculator (Utility)
- **Search intent:** "tribal knowledge," "institutional knowledge loss," "cost of employee turnover" (competing directly with existing turnover calculators, but differentiated)
- **Real problem:** existing tools price the cost of replacing the person; none price the cost of the decisions and reasoning that leave with them
- **Category:** Utility — must be scoped narrowly (decision reasoning and rationale, not general HR turnover cost) to avoid just re-building Bonusly's calculator with different branding
- **Why share/bookmark:** HR and ops leaders reuse turnover-cost numbers constantly in retention business cases; a version that's actually about decision continuity is new ammunition, not a copy

### 6. "Why Your Team Keeps Revisiting the Same Decisions" (Educational content, not a tool)
- **Search intent:** directly matches existing content I found (e.g., Save the Titanic's blog with nearly this exact title) — proven real demand
- **Real problem:** decisions get re-argued when the reasoning wasn't captured or the evidence wasn't graded honestly the first time
- **Category:** Educational, maps to the Confidence pillar in the v2 architecture
- **Why share/bookmark:** it names a frustration people recognize immediately in themselves or their leadership

### 7. Cost of Decision Delay (Educational content now, Utility later)
- **Search intent:** "analysis paralysis," "cost of delay," "decision fatigue"
- **Real problem:** real and well-documented (the Forbes/Korn Ferry material is strong), but modeling an honest dollar cost requires assuming a $ value and opportunity-cost rate per company that I can't responsibly generalize
- **Category:** Educational content first. Revisit as a Utility only once we have a defensible, non-speculative way to model it — possibly after the Initiative Readiness Score exists, since a delayed initiative's estimated value could reuse that same input
- **Why share/bookmark:** as content, it's highly quotable ("the cost of delay almost always exceeds the cost of a fixable mistake") — good LinkedIn/Decision Note material even before it's a tool

### What I would not build
- **A generic meeting-cost calculator** — see correction above; the category is saturated and undifferentiated.
- **An "initiative success predictor"** — modeling this as a scored prediction would edge into promising an outcome Jaspen can't guarantee, which conflicts directly with your "never promise savings" instruction. The real, citable failure-rate stats (Bain, McKinsey, PMI) belong in educational content as the pain-opener, not in a calculator that implies we can predict your specific outcome.
- **A general "resource allocation impact calculator"** as a first move — real problem, but the inputs are the most abstract of anything researched here (cross-initiative allocation, not a single number), and I'd want the simpler calculators above to prove the format first.

## Net effect on sequencing

Recommended build order, revised from v2's Utility list based on this research: **Decision Memory Gap and Decision Log Health Check first** (clearest white space, most directly tied to Jaspen's actual mechanism), **Initiative Readiness Score second**, **Rework Cost Estimator and Institutional Knowledge Risk Calculator third**, **Cost of Decision Delay held as content until it can be modeled honestly**, and the **generic Meeting Cost Calculator dropped or reframed**, not built as originally sequenced.
