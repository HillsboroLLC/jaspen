# Jaspen Outreach CAL-01–CAL-16 v2 vs. v3 Founder Review

Date: 2026-08-23

Scope: review-only rerun of the same CAL-01 through CAL-16 accounts. The v2 records remain in Dataverse. No thresholds were changed, and no drafting, sending, meeting booking, or autonomous routing was enabled.

## Validation status

- Power Automate v3 rerun: 16 of 16 Qualification records written successfully.
- Qualification Evidence: linked-evidence writes completed successfully. The final CAL-12 run processed 2 of 2 evidence iterations with Dataverse HTTP 201 responses.
- CAL-12 Qualification ID: `4cdff6a7-439f-f111-b8dc-6045bd01f70e`.
- Permanent DigitalOcean Function: authentication failure returns 401; authenticated structured v3 requests return 200; CAL-12 Power Automate run completed in 36 seconds.
- Rubric/prompt preserved: `jaspen-rubric-v3.0` / `qualification-v3`.

## Distribution comparison

### Product-Led User Fit

| Version | Scores by account (CAL-01 → CAL-16) | Min | Median | Mean | Max |
|---|---|---:|---:|---:|---:|
| v2 | 45, 65, 3, 3, 3, 9, 3, 3, 0, 0, 0, 3, 0, 0, 0, 0 | 0 | 3 | 8.6 | 65 |
| v3 | 4, 62, 54, 0, 0, 12, 50, 67, 33, 21, 17, 29, 25, 0, 0, 38 | 0 | 23 | 25.8 | 67 |

Frequency:

- v2: 0 × 7; 3 × 6; 9 × 1; 45 × 1; 65 × 1.
- v3: 0 × 4; all other observed values occur once (4, 12, 17, 21, 25, 29, 33, 38, 50, 54, 62, 67).

The v3 scale is operationally normalized to 0–100 and separates accounts that v2 compressed into 0/3/9 outputs.

### Purchase Readiness

| Version | Scores by account (CAL-01 → CAL-16) | Min | Median | Mean | Max |
|---|---|---:|---:|---:|---:|
| v2 | 60, 50, 50, 10, 0, 45, 45, 0, 0, 0, 0, 50, 0, 0, 0, 0 | 0 | 0 | 19.4 | 60 |
| v3 | 9, 5, 4, 4, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0 | 0 | 0 | 1.4 | 9 |

Frequency:

- v2: 0 × 9; 10 × 1; 45 × 2; 50 × 3; 60 × 1.
- v3: 0 × 12; 4 × 2; 5 × 1; 9 × 1.

No v3 account reaches the unchanged enterprise Purchase Readiness threshold of 45. This reflects the stricter requirement for explicit, dated R1–R11 evidence rather than title, remit, or strategic relevance.

### Product-Led Evidence Coverage (v3)

Scores by account: 12, 62, 75, 0, 0, 25, 75, 75, 50, 25, 25, 38, 38, 0, 0, 50.

- Range: 0–75
- Median: 31.5
- Mean: 34.4
- Frequency: 0 × 4; 12 × 1; 25 × 3; 38 × 2; 50 × 2; 62 × 1; 75 × 3.

## v3 account routes

Route reason legend (exact routing logic):

- **P** — “Normalized Product-Led User Fit meets 60; enterprise thresholds are not required for self-serve review.”
- **N** — “Enterprise Company Fit meets 55, but explicit dated Purchase Readiness is below 45.”
- **H** — “Neither the product-led review threshold nor the enterprise-ready conditions are met.”

| Account | PLUF | PL evidence coverage | Enterprise fit | Readiness | Review Route | Reason | Proceed |
|---|---:|---:|---:|---:|---|:---:|---|
| CAL-01 Lucid | 4 | 12 | 40 | 9 | hold | H | No |
| CAL-02 Tanger | 62 | 62 | 45 | 5 | product_led_review | P | Yes |
| CAL-03 AES | 54 | 75 | 50 | 4 | hold | H | No |
| CAL-04 HCA | 0 | 0 | 45 | 4 | hold | H | No |
| CAL-05 Westpac | 0 | 0 | 50 | 0 | hold | H | No |
| CAL-06 Providence | 12 | 25 | 45 | 0 | hold | H | No |
| CAL-07 GitLab | 50 | 75 | 60 | 0 | enterprise_nurture | N | No |
| CAL-08 C2i Genomics | 67 | 75 | 45 | 0 | product_led_review | P | Yes |
| CAL-09 Ascension | 33 | 50 | 40 | 0 | hold | H | No |
| CAL-10 Mount Sinai | 21 | 25 | 45 | 0 | hold | H | No |
| CAL-11 NIQ | 17 | 25 | 25 | 0 | hold | H | No |
| CAL-12 Husch Blackwell | 29 | 38 | 40 | 0 | hold | H | No |
| CAL-13 Availity | 25 | 38 | 40 | 0 | hold | H | No |
| CAL-14 FactSet | 0 | 0 | 30 | 0 | hold | H | No |
| CAL-15 Trax | 0 | 0 | 30 | 0 | hold | H | No |
| CAL-16 Biglari | 38 | 50 | 30 | 0 | hold | H | No |

Route distribution: product-led review 2; enterprise nurture 1; hold 13; enterprise ready 0.

## Accounts that changed routes

v2 did not have the explicit four-route field, so its route is reconstructed from the preserved v2 scores and Proceed result.

| Account | v2 disposition | v3 route | Exact reason for change |
|---|---|---|---|
| CAL-01 Lucid | Proceed / legacy enterprise-ready | hold | Enterprise Fit fell 55 → 40 and strict dated Readiness fell 60 → 9; PLUF 4 is below 60. |
| CAL-02 Tanger | No proceed | product_led_review | Normalized PLUF is 62, so the independent product-led route applies even though Enterprise Fit 45 and Readiness 5 do not pass enterprise routing. |
| CAL-06 Providence | Proceed / legacy enterprise-ready | hold | Enterprise Fit is 45 and strict dated Readiness is 0; neither enterprise condition passes and PLUF 12 is below 60. |
| CAL-07 GitLab | Proceed / legacy enterprise-ready | enterprise_nurture | Enterprise Fit 60 still passes, but strict dated Readiness is 0; PLUF 50 is below the product-led route. |
| CAL-08 C2i Genomics | No proceed | product_led_review | Normalized PLUF is 67, so product-led review applies independently of Enterprise Fit 45 and Readiness 0. |

All other accounts remain non-routed/held.

## Founder-review questions

### Providence and GitLab

- Providence does **not** qualify for enterprise-ready: Enterprise Fit 45 is below 55 and Readiness 0 is below 45.
- GitLab does **not** qualify for enterprise-ready: Enterprise Fit 60 passes, but Readiness 0 fails the unchanged 45 requirement. Its correct v3 route is `enterprise_nurture`.

### Tanger

Yes. Tanger now receives the intended `product_led_review` route because normalized PLUF 62 clears the product-led threshold independently of enterprise thresholds.

## Remaining contradictions and review notes

1. **CAL-12 rationale/readiness contradiction:** the saved rationale says the appointment supplies an explicit R4 signal dated `2026-03-01`, but the structured readiness array is empty and Purchase Readiness is 0. The guardrail correctly discarded the signal because the supplied evidence did not contain a complete explicit year-bearing date in the same R4 evidence item; the prose rationale was not reconciled after that discard. Numeric scoring and routing are conservative and correct, but the rationale must not claim the discarded readiness signal.
2. **Overall is informational:** some accounts can retain a Medium overall narrative while routing to `hold` or `enterprise_nurture`. This is not a routing defect because Overall is not used operationally in v3. It should remain labeled informational unless a separate operational purpose is defined.
3. **Near-threshold cases are not routing contradictions:** AES (PLUF 54) and GitLab (PLUF 50) have comparatively high product-led evidence coverage but remain below the unchanged PLUF 60 route. The numeric scores and route logic agree.
4. No other score/route contradictions were observed: all 16 routes match the frozen 60 PLUF and 55/45 enterprise rules exactly.

This report intentionally makes no threshold-change recommendation. Founder review should occur before any rubric, threshold, routing, drafting, or sending change.
