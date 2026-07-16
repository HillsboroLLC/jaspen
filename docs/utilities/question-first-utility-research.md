# Question-First Research: What People Actually Ask

Last updated: 2026-07-15
Status: research only. Nothing built. This supersedes the utility-first framing in `utility-research-findings.md` — same research ethic, but starting from real questions instead of calculator concepts, per your direction.

## How to read this document

For each real question I found evidence people ask, I recorded: the exact phrasing, whether they're hunting for a calculator/assessment/score/benchmark/checker/estimator/template/guide/something else, whether the drive behind the search is business pain, curiosity, compliance, or education, whether an interactive tool would beat an article, and whether Jaspen has an angle nobody else has. The ranked top 20 is at the end.

Two findings changed my thinking most:

1. **Two ideas from the last round have direct, live competitors I hadn't found before.** A "Decision Latency Calculator" already exists and does almost exactly what I was calling "Cost of Decision Delay." Several free "decision-making style" quizzes already exist and are well-produced. Both are noted below with what it would take to still be worth building.
2. **The best new opportunities aren't calculators about cost — they're checkers about confidence and evidence.** "How confident should I be in this decision" and "how much information do I actually need before deciding" both have huge amounts of educational content (the Colin Powell 40/70/75% rule is quoted everywhere) and **zero interactive tools**. That's real white space, and it happens to be the one thing Jaspen's actual mechanism (confidence-capped, evidence-graded scoring) can do more honestly than anyone else, because it's not a generic idea for Jaspen — it's the product's real, load-bearing methodology.

## Questions found, one by one

### "Is my team/project actually ready to commit budget to this?"
- **Exact language:** "project readiness assessment," "readiness checklist," "how do I know if my team is ready"
- **Format sought:** checklist (dominant), some PDF assessment tools — no interactive scored tool
- **Driver:** business pain (avoiding a bad budget commitment)
- **Utility > article?** Yes — every existing result is a static checklist; a real-time score is a genuine step up
- **Jaspen angle:** can tie the readiness score to the same evidence/confidence grading already in the product, and explain *why* readiness is low, not just tally checkboxes

### "What are the early warning signs a project is going to fail?"
- **Exact language:** "warning signs of project failure," "signs your project is failing"
- **Format sought:** listicle articles (extremely well-served — CIO, PMI, ProProfs, CornerStone Dynamics all have near-identical "8 signs" pieces)
- **Driver:** business pain, but the topic is already commoditized
- **Utility > article?** No — this is a saturated content category; more valuable as a feeder into the Readiness checker above than as its own asset

### "How many decisions do I make in a day, and how many are actually good ones?"
- **Exact language:** "35,000 decisions a day," "how many decisions does a CEO make"
- **Format sought:** viral statistic/curiosity content
- **Driver:** pure curiosity, not business pain
- **Utility > article?** No, and low B2B relevance despite the volume — this is consumer psychology content, not a lead-gen fit

### "How confident should I be in this decision?"
- **Exact language:** "confident decision-making," "how sure do I need to be," Colin Powell's "70 percent rule"
- **Format sought:** advice articles (Forbes Councils, HBS Working Knowledge) — **no interactive tool found anywhere**
- **Driver:** business pain and genuine uncertainty in the moment of deciding
- **Utility > article?** Yes, clearly — this is a checker, not a read
- **Jaspen angle:** this is close to a direct externalization of Jaspen's own confidence-cap mechanism (high/medium/low/assumed, each capping how much a judgment can count). Nobody else can build this credibly without an underlying system that actually grades evidence the way Jaspen's does.

### "How much information do I actually need before deciding?"
- **Exact language:** "40 percent rule," "75 percent of the information," "how much evidence is enough"
- **Format sought:** advice articles quoting the same Powell rule repeatedly — no interactive tool
- **Driver:** business pain, practical ("am I about to decide too early or waste time gathering more data I don't need")
- **Utility > article?** Yes — a short input-your-evidence-per-criterion checker mapping to a confidence read-out would be new
- **Jaspen angle:** same mechanism as above; these two could actually be one combined checker rather than two separate tools

### "What's my decision-making style?"
- **Exact language:** "decision making style quiz," "am I an analytical or intuitive decision maker"
- **Format sought:** quiz — and this space is **crowded**: Truity, TraitQuiz, ProProfs, Tesvia, AidaForm, Kent State, Varicent, Quiz-Maker all have free, well-produced versions already
- **Driver:** curiosity
- **Utility > article?** The format (quiz) is right, but it's not white space
- **Jaspen angle:** this is exactly what the existing Decision Profile / Decision Style Assessment already is. The correction here: don't expect this to win new organic traffic against eight established competitors on the bare keyword. Its value is as an on-site engagement and email-capture mechanism you already have, not a new SEO acquisition play. I'd stop thinking of it as a page that needs to rank, and keep investing in it as a homepage conversion tool.

### "What's our organizational maturity?"
- **Exact language:** "maturity assessment," "maturity model," specific variants for agile/digital/data/PM maturity
- **Format sought:** multi-step scored assessment with a report (ODI, TDWI, Cascade, NextAgile all do this well)
- **Driver:** business pain, often procurement/strategic-planning driven
- **Utility > article?** Yes, but the bar is high — competitors already deliver polished, multi-page reports with radar charts
- **Jaspen angle:** nobody has a maturity model specifically about *decision-making* maturity (all existing ones are agile/digital/data/PM-process maturity). Real white space on the specific axis, but this is the most production-heavy build on the list and needs real calibration data to be honest, not just a guessed rubric.

### "How do I run a project post-mortem, what questions do I ask?"
- **Exact language:** "post-mortem questions," "retrospective vs post-mortem"
- **Format sought:** templates and guides — but also **real interactive competitors already exist** (EasyRetro, Parabol, goretro.ai are dedicated retro-running tools, not just articles)
- **Driver:** education/process
- **Utility > article?** No — this space already has dedicated, funded competitors running the actual retro meeting. Building a competing retro tool would be starting from behind.
- **Jaspen angle:** the honest angle isn't "run the retro better," it's "what happens to what the retro surfaces" — does the lesson actually get attached to the next decision, or does it evaporate like the "lessons learned" research found. That's a content angle (and eventually a Decision Record angle), not a new tool.

### "What does indecision/decision delay actually cost us?"
- **Exact language:** "cost of indecision," "decision latency," "decision debt"
- **Format sought:** calculator — and there is a **direct existing competitor**: a "Decision Latency Calculator" (earlywarningindex.com) built specifically for CEOs/boards/VCs to quantify delayed-decision cost, plus a "DecideFast Culture Performance Tool" in the same space citing "$1.3M per 1,000 employees annually" lost to indecision
- **Driver:** business pain, real and validated (someone already built and markets this)
- **Utility > article?** The format is proven, but it's not white space anymore
- **Jaspen angle:** only worth building if it goes further than the competitor — e.g., not just "here's your delay cost" but "here's specifically which missing evidence or unresolved assumption is causing the delay," which ties to Jaspen's actual mechanism in a way a generic latency calculator can't. Without that extra layer, I'd skip it — copying a live competitor's exact concept isn't a good use of build time.

### "Should I build this myself or buy it?"
- **Exact language:** "build vs buy," "build vs buy decision matrix," "build vs buy calculator"
- **Format sought:** calculator/matrix — **already well-served**: Demand Metric, Neontri, Brilworks, Adaptive, and Thoughtworks all have free tools or frameworks
- **Driver:** business pain, but for a narrow (software/technical) audience
- **Utility > article?** The category is proven but crowded
- **Jaspen angle:** more valuable as a worked-example article showing Jaspen's rubric-building approach applied to this one universally-recognized decision type, than as a competing calculator

### "How do I explain/justify this decision to the board, months later?"
- **Exact language:** "decision papers," "board decision-making process," rarely phrased as a question — this lives mostly in board-governance content (Board Intelligence, Harvard Corporate Governance blog)
- **Format sought:** guides and templates — no interactive tool found that generates a defensible rationale on demand
- **Driver:** business pain, specifically leadership/board-facing, sometimes compliance-adjacent (governance, audit trail)
- **Utility > article?** Borderline — a lightweight rationale template could work as content; a full generator risks just being a thin preview of what Jaspen already does in-app, which needs care to avoid feeling like bait-and-switch
- **Jaspen angle:** very strong. Jaspen's own scoring already decomposes into criteria, weights, evidence, and confidence — literally the structure a good decision paper needs. This is one of the clearest "show, don't tell" opportunities on the list.

### "Why does my team keep revisiting the same decisions?"
- **Exact language:** matches existing competitor content almost exactly (found a blog post titled nearly this)
- **Format sought:** article
- **Driver:** business pain, high recognition ("yes, that's us")
- **Utility > article?** No — this is squarely educational content, and cheap to produce
- **Jaspen angle:** direct match to the Confidence pillar in the content architecture

## Ranked top 20

Ranked holistically against your five criteria (real search demand, business pain, differentiation, natural progression into Jaspen, confidence we can build it honestly) — not by demand alone, since you were explicit that traffic isn't the goal.

1. **Decision Confidence Checker** ("How confident should you be in this decision?") — Utility. No competitor tool found; directly externalizes Jaspen's actual mechanism; high buildability.
2. **Evidence Sufficiency Checker** ("Do you actually have enough information to decide?") — Utility, possibly combined with #1. Same white space, same mechanism fit, huge quotable content already validating the question (Powell rule).
3. **Decision Memory Gap** (estimate what re-deciding already-decided things is costing you) — Utility. No interactive competitor found in the decision-log space; strong tie to Decision Records.
4. **Decision Log Health Check** (short self-check, documentation-gap score) — Assessment. Cheapest to build well of the top group; strong differentiation; low risk.
5. **Initiative Readiness Score** — Utility, interactive and scored rather than a checklist. Proven demand; meaningful (not huge) differentiation via interactivity.
6. **Institutional Knowledge / Decision-Continuity Risk Calculator** — Utility. Strong pain and Jaspen fit; existing turnover calculators mean it needs a decision-specific (not generic HR) framing to stay differentiated.
7. **"Why does my team keep revisiting the same decisions?"** — Educational content. Proven direct demand; cheap; strong fit to the Confidence pillar.
8. **Organizational Decision Maturity Assessment** — Assessment, flagship. Highest ceiling on the list, but the lowest near-term build confidence — needs real calibration data. Sequence last on purpose.
9. **Decision Confidence Assessment** (org-wide pattern, distinct from #1's per-decision checker) — Assessment. Good complement to #1, distinct enough to justify separately.
10. **Decision Paper / Board Memo content (+ lightweight template)** — Educational content, possibly a light utility later. Strong differentiation, needs care not to feel like a teaser for the paid product.
11. **"How much evidence do I need to decide?" article** — Educational content that sets up #2. Rich, quotable existing material to build on.
12. **Rework Cost Estimator** — Utility. Solid and safe, but more generic project-management pain than something uniquely Jaspen.
13. **Team Decision Style Assessment** — Assessment, extends the existing Decision Profile. Real, but shares a crowded keyword space; mainly valuable as product engagement, not new acquisition.
14. **Decision-Making Frameworks Compared** — Educational, router/authority content. Useful connective tissue, low uniqueness on its own.
15. **"How to justify a decision to the board" article** — Educational content, narrower audience, complements #10.
16. **Cost of Decision Delay / Decision Latency calculator** — Utility, but a direct competitor already exists and does this. Only pursue if it goes further (diagnosing the specific cause, not just pricing the delay).
17. **Build vs. Buy worked-example content** — Educational, not a calculator — the calculator space here is already crowded with real competitors.
18. **Post-mortem / retrospective questions guide** — Educational content only. Dedicated, funded competitor tools already run this workflow; don't compete on the tool, compete on "what happens after."
19. **"Early warning signs your project will fail" content** — Real demand but the most saturated topic on this list; feed it into #5 rather than building it standalone.
20. **Executive Meeting Cost Calculator** — Considered and rejected again. At least ten free, well-built competitors exist; no natural bridge into a Jaspen conversation. Listed here only so the "no" is on the record with its reasoning.

## What this changes about prior recommendations

- **Two new ideas (#1 and #2) outrank everything from the previous two rounds.** They're the closest thing on this entire list to a direct expression of what Jaspen's product actually, uniquely does — confidence-capped, evidence-graded judgment — rather than a general business calculator that happens to be Jaspen-branded.
- **The Decision Style Assessment (existing Decision Profile) needs a status correction, not a build decision** — it's good, keep it, but stop treating it as an SEO growth lever. It's an on-site conversion tool in a very crowded organic category.
- **Cost of Decision Delay drops sharply** now that a live, named competitor does almost exactly that.
- **Post-mortem/retrospective tooling is off the table as a utility** — that space already has dedicated, funded competitors; recommend content only, and only the "what happens after" angle.
