# Cost of Turnover utility

Jaspen's first public business utility. Route: `/tools/cost-of-turnover`
(production: https://jaspen.ai/tools/cost-of-turnover).

Source of truth for all numbers, questions, formulas, and provenance:
`docs/utilities/Utility_Lead - Cost_of_Turnover (refined).xlsx` (methodology v1.0,
frozen). Do not change formulas, categories, benchmarks, or defaults without
flagging them for review.

## Architecture (built to be reused by future utilities)

Concerns are deliberately separated so the calculation is never hard-coded into
presentation:

```
data/         benchmarks.js   Benchmark library + provenance (id, value, source, year,
                              methodology, limitation, type, reliability, status, dates)
              roles.js        Role taxonomy, salary defaults, executive classification
config/       questions.js    Step/question config + conditional-visibility predicates
              seo.js          Title, description, canonical path, JSON-LD structured data
engine/       calculator.js   Pure calc engine: components, low/mid/high, subtotals, total,
                              double-count safeguards, top drivers  (NO React)
              builtUsing.js   Cost-weighted 3-way "Estimate Built Using" composition (=100%)
              formatting.js   Currency/percent helpers
              version.js      CALC_VERSION
hooks/        useCostOfTurnover.js   Input state, overrides, derived result + composition
services/     analytics.js    Funnel events, source = cost_of_turnover_utility
              leadService.js  Lead attribution via the shared /public/leads pipeline
              savedEstimate.js Snapshot + account/local persistence (graceful fallback)
components/   CostOfTurnoverPage.jsx + Stepper, steps/*, AssumptionField, ProvenanceBadge,
              SourceDetail, BuiltUsingBar, MethodologyModal, SaveEstimatePanel,
              BenchmarkContributionPanel, JaspenCta
__tests__/    calculator / builtUsing / config
```

## Key guarantees (enforced by tests)

- Sample scenario reconciles to the workbook: **$86,694 midpoint** (documented
  tolerance: $1/component, $2/total) — see `calculator.test.js`.
- The total is the sum of additive components only; subtotals are never re-added.
- Context rediscovery is defined as incremental-to-ramp only (no double count).
- Published Benchmark vs Research-Based Estimate labels are preserved per value.
- "Estimate Built Using" always totals 100% and is a composition, not accuracy.
  Overriding an assumption moves that field into "Your Organization's Inputs".

## Backend (optional persistence)

`backend/app/routes/tools.py` + `SavedUtilityEstimate` model + migration
`a1b2c3d4e5f6_add_saved_utility_estimates.py`. The utility is fully usable
without it (anonymous users are never persisted; the authenticated save degrades
to a local snapshot / HTTP 503 until the migration is applied).
