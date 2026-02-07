# Verify Scorecard Rendering (Dev Diagnostic)

## Purpose
Confirm which analysis object the Score tab is rendering and whether detailed sections are present.

## Where the log lives
- `frontend/src/Market/MarketIQ/workspace/MarketIQWorkspace.jsx`

## How to reproduce
1. Run the frontend in development mode so `process.env.NODE_ENV === "development"`.
2. Open MarketIQ and navigate to the Score tab.
3. Open the browser console.
4. Look for the log entry labeled `"[ScoreDashboard activeAnalysis]"`.

## Expected output fields
The log prints a single object with:
- `activeAnalysisName` (string label of the variable)
- `activeAnalysisKeys` (top-level keys)
- `scoresKeys` (keys in `activeAnalysis.scores`)
- `financialImpactKeys` (keys in `activeAnalysis.financial_impact`)
- `sections` (booleans for detailed sections)

## Good vs Bad output
Good
1. `activeAnalysisKeys` includes items like `decision_framework`, `investment_analysis`, `npv_irr_analysis`, `valuation`, `before_after_financials`, `metrics`.
2. `sections` has `true` for most of those fields.

Bad
1. `activeAnalysisKeys` only includes `overall_score` or `market_iq_score` plus minimal fields.
2. `scoresKeys` is empty or missing, and `sections` flags are all `false`.
