# Jaspen Outreach Qualification Calibration Plan

## Purpose

This plan defines the first founder-reviewed calibration batch for the Jaspen Outreach qualification workflow. The batch is strictly review-only: it may create Prospect, Evidence Item, Qualification, and Qualification Evidence records, but it must not create approved outreach, invoke the sending flow, or send email.

The purpose is to test whether the AI judges real prospects the way Jaspen intends before qualification is connected to drafting, Apollo import, or any scaled automation.

## Governing source hierarchy

1. **Jaspen Sales Playbook & ICP Brief** — primary source for ICP intent, decision-shape fit, offers, personas, and routing philosophy.
2. **Jaspen Sales Operating System** — operational source for researched accounts, contacts, evidence, working scores, and observed readiness signals.
3. **Jaspen Scoring Method - Unify Implementation Brief** — starting hypothesis for weights, thresholds, evidence coverage, decay, and routing. Its weights and thresholds are calibration inputs, not validated truth.

When the sources appear to conflict, preserve the Playbook's product-led principle: observable decision need and decision shape matter more than title, company size, or enterprise characteristics alone.

## Qualification model

Qualification must preserve three distinct judgments rather than collapsing them into one opaque score.

### 1. Product-led decision-shape fit

Evaluate whether the available evidence indicates a consequential, ambiguous, or cross-functional decision that Jaspen can help structure. Use the Playbook's product-led fit criteria as the governing interpretation. Title alone is not evidence of need.

### 2. Enterprise company fit

Evaluate the company against the A1-A15 criteria in the Scoring Method. Preserve the four bands:

- Tier A: 75-100
- Tier B: 55-74
- Tier C: 35-54
- Tier D: 0-34

The A1-A5 core criteria remain the strongest portion of this axis. A company must not reach Tier A from desk research alone when required criteria need discovery validation.

### 3. Purchase readiness

Evaluate dated R1-R11 signals independently from fit. Apply source confidence and recency/decay principles. A strong fit with no current signal is not the same state as a weak fit with a recent trigger.

**Never average Company Fit and Purchase Readiness.** Preserve both axes and route from the combination.

## Evidence guardrails

- The model may use only Evidence Item records supplied from Dataverse for the selected Prospect.
- Every factual claim in a Qualification must be attributable to one or more linked Evidence Item records.
- Every Qualification must create Qualification Evidence junctions for the Evidence Items actually used.
- Missing evidence is blank/unknown, not zero. Zero means reliable evidence that the criterion is absent or contradicted.
- `N/A` is permitted only where the source method explicitly allows it.
- The model must not infer private facts, fabricate events, or convert a job title into an unsupported need signal.
- Conflicting evidence must be disclosed in the rationale and should reduce confidence.
- Low evidence coverage must produce an explicit uncertainty statement and a research recommendation rather than false precision.

## Routing matrix for calibration

Use the working thresholds from the Scoring Method as hypotheses:

| Company Fit | Purchase Readiness | Calibration route |
|---|---|---|
| 55+ | 45+ | Candidate for founder-reviewed high-touch outreach |
| 55+ | Below 45 | Nurture / monitor for a trigger |
| Below 55 | 45+ | Product-led or self-serve route; founder review required |
| Below 55 | Below 45 | Do not pursue now |

No route in this calibration plan authorizes sending.

## First calibration batch

Select 16 existing researched records from the Sales Operating System workbook. The set should be intentionally balanced rather than simply taking the highest-ranked accounts.

The current workbook does not contain a record at or above the Scoring Method's provisional Purchase Readiness threshold of 45. The highest cached readiness score is below 20. That is an important calibration finding: do not relabel these records “high readiness” merely to fill a matrix. Use the strongest available signals as **relative-high readiness** cases while separately testing whether the threshold or readiness normalization needs adjustment.

Freeze this first proposed sample:

| Calibration segment | Account ID | Account | Workbook fit | Workbook readiness | Why included |
|---|---|---|---:|---:|---|
| Strongest available readiness | ACC-0047 | Lucid | 70.0 | 17.7 | Multiple recent signals plus an identity/confidence warning |
| Strongest available readiness | ACC-0294 | Tanger | 68.9 | 10.4 | Upper readiness tail with solid fit |
| Strongest available readiness | ACC-0452 | The AES Corporation | 74.0 | 10.3 | Fit-cap boundary plus current signals |
| Strongest available readiness | ACC-0059 | HCA Healthcare | 56.3 | 9.4 | Just above the fit threshold with stronger signals |
| High fit / no current signal | ACC-0038 | Westpac Banking Corporation | 71.8 | 0.0 | Strong structural fit without a current trigger |
| High fit / no current signal | ACC-0057 | Providence | 72.3 | 0.0 | Healthcare account with strong fit and no readiness |
| High fit / no current signal | ACC-0074 | GitLab Inc. | 69.4 | 0.0 | Technology account with no current trigger |
| High fit / no current signal | ACC-0052 | C2i Genomics | 63.3 | 0.0 | Smaller/sector-varied strong-fit case |
| Threshold edge | ACC-0043 | Ascension | 54.7 | 0.0 | Immediately below the provisional fit threshold |
| Threshold edge | ACC-0072 | Mount Sinai Health System | 57.5 | 0.0 | Immediately above the provisional fit threshold |
| Threshold edge | ACC-0082 | NIQ (NielsenIQ) | 53.9 | 0.0 | Borderline negative case |
| Threshold edge | ACC-0034 | Husch Blackwell LLP | 57.9 | 3.6 | Borderline fit with a weak active signal |
| Lower fit / no current signal | ACC-0031 | Availity, LLC | 48.4 | 0.0 | Evidence-rich marginal-fit case |
| Lower fit / no current signal | ACC-0048 | FactSet Research Systems Inc. | 49.6 | 0.0 | Marginal-fit control |
| Lower fit / no current signal | ACC-0050 | Trax Credit Union | 39.9 | 0.0 | Low Tier C control |
| Lower fit / no current signal | ACC-0324 | Biglari Holdings Inc. | 30.0 | 0.0 | Tier D negative control |

Within those groups, include a mix of:

- evidence-rich and evidence-poor records;
- recent and stale readiness signals;
- executive and non-executive contacts;
- obvious, ambiguous, and negative cases;
- at least two records with conflicting evidence (Lucid is one required case; identify a second during evidence packaging);
- at least two records where the correct answer should be “insufficient evidence.”

Do not import the entire workbook for the first pass. Freeze the 16-record sample and version it so prompt and rule changes can be compared against the same cases.

## Dataverse batch record requirements

For each selected case:

1. Create or update one Prospect record with stable source identifiers.
2. Create separate Evidence Item records for each source fact, including source URL/reference, observed date, evidence date, confidence, and source type where available.
3. Run `Jaspen - Qualify Prospect` only after the founder-review evidence set is complete.
4. Store the structured Qualification output.
5. Create Qualification Evidence junctions only for evidence actually used.
6. Preserve the prompt/rubric version and qualification timestamp.
7. Do not create or approve an Outreach Message from the batch.

## Founder review fields

Capture the following for each case in the review set:

| Field | Purpose |
|---|---|
| Prospect | Stable record under review |
| Evidence Item IDs | Exact evidence presented to the model |
| AI product-led fit | Structured model judgment |
| AI company-fit score/band | Independent fit result |
| AI readiness score/band | Independent readiness result |
| AI evidence confidence/coverage | Strength and completeness of support |
| AI rationale and outreach angle | Concise, evidence-grounded explanation |
| AI route | High-touch, nurture, product-led, or do not pursue |
| Founder expected result | Human benchmark before reviewing the AI result where practical |
| Founder decision | Accept, adjust, or reject |
| Disagreement reason | Evidence miss, rubric miss, weight issue, threshold issue, or prompt issue |
| Corrected result | Founder-approved calibration label |
| Prompt/rubric version | Reproducibility and comparison |

## Acceptance gates before drafting or scale

The batch is successful only when all of the following are true:

- 100% of qualifications are traceable to Dataverse Evidence Items.
- 0 invented facts or unsupported claims appear in qualifications.
- 100% of calibration runs remain disconnected from sending.
- Low-coverage records are labeled uncertain rather than given false precision.
- Company Fit and Purchase Readiness remain visibly separate.
- No record reaches Tier A solely from desk research when discovery validation is required.
- At least 80% of the 16 cases match the founder's expected routing direction, with every disagreement categorized.
- Re-running an unchanged case under the same version produces materially consistent structured output.

If any hard guardrail fails, stop the batch, correct the workflow or prompt, and rerun the same frozen cases before adding new records.

## Implementation note

The current MVP Qualification table exposes useful review fields (`Overall Qualification`, `Use-Case Fit`, `Readiness Signals`, `Evidence Confidence`, `Recency`, `Remit Connection`, rationale, angle, and proceed flag). Before the 16-record calibration batch, extend the schema or the structured output so Company Fit and Purchase Readiness are stored as separate scored axes with evidence coverage and rubric version. Do not force the richer two-axis method into the current single overall label.
