# Published Benchmarks for the Jaspen-Specific Cost Categories

**Purpose:** Give the four Jaspen differentiators (Knowledge Transfer, Context Rediscovery, Institutional Memory, Project Disruption) the same sourced foundation the standard turnover inputs already have. Every figure below carries a source, year, methodology, and limitation, exactly like "SHRM found cost per hire is $5,475."

**Read this first — the honest headline:** No organization has published a benchmark that says "context rediscovery after a departure takes X hours" or "institutional-memory reconstruction takes Y coworker hours." Those specific *event* costs don't exist as citable numbers. What *does* exist, and is well-measured, are two things we can defensibly build on:

1. **Ongoing per-worker rates** — how many hours a week the average knowledge worker already loses searching for and recreating information (APQC, McKinsey, Panopto).
2. **Structural facts about a departure** — how long ramp takes, how much knowledge is undocumented, how much sits with one person (Gallup, Gartner, Panopto).

The defensible default is the *published rate* multiplied by the *departure structure* — which is exactly the behavioral model (helpers × weeks × hours/week; searches/week × ramp weeks). That turns an invented number into a derived, cited one.

**Reliability tiers used below:**
- **A – Primary:** named study, disclosed sample/method, usable as a default.
- **B – Proxy:** solid primary data measuring something adjacent; use as a defensible proxy, not a direct measure.
- **C – Secondary:** figure is widely repeated but we only found it via secondary citation; verify the primary source before quoting it publicly.

---

## 1. Knowledge Transfer

### Overlap / handover period
- **2–4 weeks for individual-contributor roles; ~30 days for most roles; 60–90 days for senior or specialized roles.** Practitioner best-practice, synthesized across HR handover guides (Enboarder, SHRM offboarding guidance, ShiftFlow 12-week KT plan). **Tier B/C** — this is consensus practice, not a controlled study, so present it as "typical planned overlap," not a measured average.
  - *Limitation:* only available when a departure is planned; unplanned exits get zero overlap. Your tool should ask "planned / partial / none" (it already does) and set this to 0 for unplanned exits.

### Time to full productivity (bounds the transfer + ramp window)
- **Median 8.2 months to full productivity for mid-level professionals; 12+ months for many roles** — Gallup, 2024 workforce data. **Tier A.**
- **~8 weeks (simple) to 20 weeks (typical professional) to 26+ weeks (executive/complex)** — cited to MIT Sloan Management Review. **Tier B** (secondary citation of MIT Sloan; verify exact figure before quoting).
- **Structured onboarding cuts time-to-productivity 30–50%** — Brandon Hall Group, 2023. **Tier B.**
  - *Use:* this is your ramp-duration benchmark by complexity — Gallup's 8.2 months is a clean, quotable anchor.

### Onboarding / mentor time
- No clean published "mentor hours per new hire" figure exists. Strongest proxy: the reconstruction/help rates in Section 3 (Panopto 5.3 hrs/week of coworker time; APQC 8.2 hrs/week). **Tier B.**

---

## 2. Context Rediscovery

This is the best-supported category — the ongoing "time lost finding and recreating information" literature is deep.

- **8.2 hours per week** looking for, recreating, and duplicating information and expertise (breakdown: 3.6 hrs internal communication, 2.8 hrs looking for/requesting information, 2.2 hrs unproductive meetings) — **APQC, "Fixing Process & Knowledge Productivity Problems," 2021, n = 982 full-time knowledge workers.** **Tier A.** This is your anchor for recreating/searching time.
- **9.3 hours per week (1.8 hrs/day, ~20% of the workweek)** searching for and gathering information — **McKinsey Global Institute** (widely cited). **Tier A/B** — McKinsey's own; commonly quoted, verify the exact MGI report page before public use.
- **~5 hours per week** searching for documents, with nearly half of searches unsuccessful — **IDC, 2012.** **Tier B** (dated, but directionally consistent and often cited).
  - *Use:* a replacement rebuilding lost context sits **at or above** these averages, because they lack the tenure that makes a veteran efficient. So an ongoing rate of ~8–9 hrs/week is a conservative floor for a new person's rediscovery burden. Multiply by the ramp window (Gallup 8.2 months ≈ 35 weeks) and apply the double-count rule (only the *incremental* time beyond a normal ramp curve).
  - *Limitation:* these are averages for *all* workers, not specifically post-departure replacements. That's why they're a floor/proxy, not a direct measure — and why your behavioral survey (events → hours) is the right way to calibrate the exact multiplier.

---

## 3. Institutional Memory

### Documentation coverage (how much is undocumented — the size of the risk)
- **70–80% of enterprise knowledge is tacit** — never written down in retrievable form — **Gartner, 2024.** **Tier B** (found via secondary citation of Gartner 2024; verify report before quoting). Implies only ~20–30% is documented.
- **42% of institutional knowledge is unique to the individual** — acquired for their current role, not shared by any coworker — **Panopto Workplace Knowledge & Productivity Report, 2018, n = 1,001** U.S. employees (orgs of 200+, 5+ years' experience). **Tier A.** This is a strong, quotable default for "share of a role's knowledge at risk when they leave."

### Time recreating undocumented knowledge / coworker reconstruction
- **5.3 hours per week** wasted waiting for information from colleagues or recreating existing institutional knowledge — **Panopto, 2018, n = 1,001.** **Tier A.** Best proxy for the *reconstruction* line (coworker time). Combine as: affected coworkers × weeks × (a fraction of) 5.3 hrs.
- **Inefficient knowledge sharing costs a large U.S. business ~$47 million/year** — Panopto, 2018. **Tier A** (from the same study) — useful as a *marketing* anchor, not a per-departure default.

### Lessons-learned reuse
- **78% of high-performing organizations report that capturing and applying lessons learned significantly increases project success** — PMI. **Tier B.** Note the framing: it measures *value of capturing*, not a *reuse rate*. A clean "% of lessons actually reused" figure does not appear to be published — flag as a gap.

### Knowledge loss due to attrition (context / marketing, not a per-departure default)
- **Institutional knowledge loss costs U.S. companies ~$1.3 trillion/year** — attributed to Deloitte, 2024. **Tier C** — secondary citation only; verify before using publicly.
- **Mid-cap S&P 500 firms lose $228–355M/year** to attrition and disengagement — attributed to McKinsey. **Tier C** — secondary; verify.

---

## 4. Project Disruption

The thinnest category for direct benchmarks — be honest about it and lean on vacancy/delay proxies plus labor-only modeling.

- **~$500/day in lost productivity for a typical open role; ~$1,154/day for a $150k engineer at a 2× impact multiplier** — cost-of-vacancy analyses (DockYard, InterviewCost, Built In). **Tier B.** Proxy for delay cost per vacant day.
- **Total cost of a vacant specialist/engineering role reaches 2–4× annual salary** once lost productivity, delayed releases, and team drag are included — engineering cost-of-vacancy literature. **Tier B.**
- **24% of organizations delayed or canceled a strategic initiative due to talent constraints** — PMI (2012 survey). **Tier B/C** (dated). Proxy for "share of active projects materially disrupted."
- **A team's efficiency can drop ~48% after a senior employee leaves, with a ~6-month on-ramp** — appears in secondary knowledge-worker-attrition write-ups. **Tier C** — verify the primary source before relying on it; it's a striking figure but currently traceable only to secondary blogs.
  - *Recommendation:* keep Project Disruption **labor-only** in v1 (added team hours × blended rate), as the workbook already specifies. Use these figures to sanity-check magnitude, not as the formula. Don't claim to predict project failure or lost project value.

---

## Recommended defaults (research-anchored, still label "provisional until user-calibrated")

| Workbook variable | Current placeholder | Research-anchored default (low / mid / high) | Anchored to |
|---|---|---|---|
| Knowledge transfer overlap | 40 hrs | IC: 2–4 wks · most: ~4 wks · senior: 6–12 wks of *part-time* overlap; 0 if unplanned | HR handover practice (Tier B/C) |
| Ramp duration | 4 months | 5 / 8 / 12 months by complexity | Gallup 8.2 mo (Tier A) |
| Context rediscovery | 160 hrs | ~4 / ~8 / ~9 hrs per week × ramp weeks, incremental only → ≈ 80 / 130 / 180 hrs | APQC 8.2, McKinsey 9.3 (Tier A/B) |
| Institutional-memory reconstruction | 60 coworker hrs | helpers × weeks × (share of 5.3 hrs/wk) → keep ~40 / 60 / 90 hrs | Panopto 5.3 hrs/wk (Tier A) |
| Share of role knowledge at risk | — (new) | ~42% unique to individual | Panopto (Tier A) |
| Documentation coverage | — (new) | ~20–30% explicit / 70–80% tacit | Gartner 2024 (Tier B) |
| Project disruption | 24 hrs/project | labor-only; sanity-check vs ~$500–1,154/day vacancy | Cost-of-vacancy (Tier B) |

**Notes:** Your original placeholders hold up better than expected — rediscovery at 160 was slightly high (research supports ~130 mid), and reconstruction at 60 lands right in the Panopto-anchored range. Two of your metrics (share of knowledge unique to a person: 42%; documentation coverage: 20–30%) are *new, strong, Tier-A/B facts* you can add as headline stats.

## Honest gaps to close before launch
1. **No direct per-departure benchmark exists** for rediscovery, reconstruction, or disruption hours. Your behavioral survey (events → hours) is what converts the ongoing published rates into a defensible per-event default. Do it.
2. **Verify Tier-C figures** ($1.3T Deloitte; $228–355M McKinsey; 48% team-efficiency drop) against primary sources before any public use.
3. **Gartner 70–80% and McKinsey 9.3 hrs** are strong but were reached via secondary citations here; pull the primary report page for the footnote.

## Sources
- APQC, *Fixing Process & Knowledge Productivity Problems* (2021, n=982) — https://www.apqc.org/blog/km-makes-knowledge-workers-more-productive-and-less-stressed-out and https://www.apqc.org/about-apqc/news-press-release/apqc-survey-finds-one-quarter-knowledge-workers-time-lost-due
- Panopto, *Workplace Knowledge & Productivity Report* (2018, n=1,001) — https://www.panopto.com/company/news/inefficient-knowledge-sharing-costs-large-businesses-47-million-per-year/
- McKinsey Global Institute, time spent searching/gathering information — via https://cottrillresearch.com/various-survey-statistics-workers-spend-too-much-time-searching-for-information/
- Gartner, enterprise knowledge is 70–80% tacit (2024) — via https://atlan.com/know/data-for-ai/institutional-knowledge-loss/
- Gallup, time to full productivity ~8.2 months (2024) — https://www.gallup.com/workplace/246242/essential-ingredients-effective-onboarding-program.aspx
- PMI, lessons learned and talent-constraint project delays — https://www.pmi.org/learning/library/business-benefits-value-lessons-learned-7116 and https://www.pmi.org/learning/library/support-knowledge-transfer-pmos-10206
- IDC (2012), ~5 hrs/week searching for documents — via https://www.valamis.com/blog/why-do-we-spend-all-that-time-searching-for-information-at-work
- Cost-of-vacancy analyses — https://dockyard.com/blog/2024/11/26/vacancy-productivity-untold-recruiting-costs and https://builtin.com/recruiting/cost-of-vacancy
- Knowledge-transfer overlap practice — https://enboarder.com/blog/checklist-knowledge-transfer/ and https://www.shrm.org/topics-tools/news/hr-magazine/capture-what-employees-know-before-they-leave-the-company
- Deloitte $1.3T / McKinsey $228–355M (secondary, verify) — via https://atlan.com/know/data-for-ai/institutional-knowledge-loss/ and https://gadallon.substack.com/p/the-real-cost-of-knowledge-worker
