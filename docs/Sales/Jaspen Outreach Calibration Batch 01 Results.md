# Jaspen Outreach Qualification Calibration — Batch 01 Results

Date: 2026-08-23  
Mode: Founder review only  
Rubric: `jaspen-rubric-v2.0`  
Prompt: `qualification-v2`  
Frozen routing thresholds: Enterprise Company Fit **55**; Purchase Readiness **45**

## Governing controls

- Product-Led User Fit, Enterprise Company Fit, and Purchase Readiness remained separate dimensions.
- Evidence Coverage and Rubric Version were recorded in the structured output.
- The model used only the 25 frozen Evidence Items associated with the 16 calibration Prospects.
- No drafting, sending, meeting booking, routing change, or threshold change was enabled.
- `proceed_to_outreach` is a review-only observation, not an authorization to contact anyone.

## Batch results

| # | Account | Baseline company fit | Baseline readiness | Product-led user fit | Enterprise company fit | Purchase readiness | Evidence coverage | Evidence confidence | Overall | Both thresholds |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| 01 | Lucid | 70.0 | 17.7 | 70 | 70 | 85 | 60 | 60 | Medium | Yes |
| 02 | Tanger | 68.9 | 10.4 | 65 | 40 | 85 | 40 | 75 | Medium | No |
| 03 | The AES Corporation | 74.0 | 10.3 | 70 | 45 | 65 | 30 | 70 | Medium | No |
| 04 | HCA Healthcare | 56.3 | 9.4 | 55 | 58 | 30 | 30 | 75 | Medium | No |
| 05 | Westpac Banking Corporation | 71.8 | 0.0 | 70 | 38 | 20 | 40 | 60 | Low | No |
| 06 | Providence | 72.3 | 0.0 | 80 | 72 | 30 | 100 | 90 | Medium | No |
| 07 | GitLab Inc. | 69.4 | 0.0 | 75 | 65 | 60 | 35 | 70 | Medium | Yes |
| 08 | C2i Genomics | 63.3 | 0.0 | 85 | 40 | 10 | 30 | 90 | Low | No |
| 09 | Ascension | 54.7 | 0.0 | 25 | 56 | 20 | 25 | 70 | Medium | No |
| 10 | Mount Sinai Health System | 57.5 | 0.0 | 30 | 57 | 10 | 30 | 60 | Medium | No |
| 11 | NIQ (NielsenIQ) | 53.9 | 0.0 | 20 | 30 | 15 | 25 | 60 | Low | No |
| 12 | Husch Blackwell LLP | 57.9 | 3.6 | 65 | 62 | 60 | 40 | 70 | Medium | Yes |
| 13 | Availity, LLC | 48.4 | 0.0 | 25 | 54 | 10 | 20 | 70 | Low | No |
| 14 | FactSet Research Systems Inc. | 49.6 | 0.0 | 20 | 25 | 10 | 20 | 70 | Low | No |
| 15 | Trax Credit Union | 39.9 | 0.0 | 15 | 25 | 10 | 30 | 40 | Low | No |
| 16 | BIGLARI HOLDINGS INC. | 30.0 | 0.0 | 10 | 30 | 10 | 40 | 70 | Low | No |

## Observed distributions

| Dimension | Minimum | 25th percentile | Median | 75th percentile | Maximum | Mean |
|---|---:|---:|---:|---:|---:|---:|
| Product-Led User Fit | 10 | 20 | 60 | 70 | 85 | 48.8 |
| Enterprise Company Fit | 25 | 30 | 49.5 | 62 | 72 | 47.9 |
| Purchase Readiness | 10 | 10 | 20 | 60 | 85 | 33.1 |
| Evidence Coverage | 20 | 25 | 30 | 40 | 100 | 37.2 |
| Evidence Confidence | 40 | 60 | 70 | 75 | 90 | 68.8 |

Additional counts:

- 7 of 16 reached Enterprise Company Fit 55.
- 5 of 16 reached Purchase Readiness 45.
- 3 of 16 reached both provisional thresholds: Lucid, GitLab, and Husch Blackwell.
- Overall qualification distribution: 9 Medium, 7 Low, 0 High.
- The frozen workbook baseline had 10 of 16 at or above 55 on company fit and 0 of 16 at or above 45 on its readiness score.

The baseline Purchase Readiness score and the AI's 0–100 Purchase Readiness judgment are not directly interchangeable. The gap is an observed calibration issue, not evidence that the threshold should be changed.

## Founder-review observations

1. **The 45 threshold should remain frozen for now.** The batch shows that the model can produce both high and low readiness scores; the unresolved question is how much signal evidence should be sufficient to reach 45.
2. **GitLab is the clearest edge case.** It reached 60 readiness from one fresh hiring/mandate signal and passed both thresholds despite only 35% Evidence Coverage. Founder review should decide whether that is an acceptable outreach hypothesis or whether low coverage must block routing independently of the score.
3. **Lucid passed despite identity uncertainty.** Its rationale correctly retained the identity warning and a 70-point cap, but the two numeric thresholds still yielded `true`. This tests whether identity/gating conditions must become explicit hard stops later.
4. **Tanger and AES show the dimensions separating correctly.** Both had strong readiness judgments but missed Enterprise Company Fit, so they did not pass both thresholds.
5. **Providence's 100 Evidence Coverage deserves review.** It is an outlier relative to the rest of the batch and should be checked against the intended meaning of coverage before the rubric is considered calibrated.
6. **The AI company-fit distribution is materially lower than the workbook baseline.** Mean Enterprise Company Fit was 47.9 versus a baseline mean of 58.6. That may reflect stricter treatment of unknowns and the discovery-validation gate rather than a bad threshold.

## Power Automate transport finding

All Dataverse-side steps in the authenticated qualification flow succeeded: selected Prospect retrieval, Evidence Item retrieval, and evidence shaping. The HTTP intelligence action then received `403 Forbidden` with a Cloudflare challenge page. Consequently, the cloud flow did not create Qualification or Qualification Evidence rows for this batch.

The structured batch was therefore executed directly on the same DigitalOcean intelligence code and securely stored OpenAI environment. The observed scores above are valid service outputs, but they are **not yet written back to Dataverse**.

Recommended infrastructure correction before another cloud-flow run:

- Prefer a dedicated origin hostname for the intelligence endpoint that Microsoft Power Automate can reach without a browser challenge, while retaining TLS, the shared-secret header, request-size limits, rate limiting, and logging; or
- Add a narrowly scoped Cloudflare rule that skips interactive challenge behavior only for the qualification endpoint, while keeping authentication and non-interactive security controls in place.

Do not rerun the batch through Power Automate until that transport path is corrected. Do not change thresholds, routing logic, drafting, or sending as part of the transport fix.
