# Frontend Scorecard Trace (Jaspen)

## Scorecard UI entry point (Score tab)
- **Route → Workspace**: `frontend/src/App.js` renders `JaspenWorkspace` at `/new` (with `/strategy` redirect).
- **Score tab**: `frontend/src/jaspenInterface/Workspace/JaspenWorkspace.jsx`
  - Tab button: `<TabButton id="summary" label="Score" />`
  - Rendered view:
    - `activeTab === 'summary'` → `<ScoreDashboard ... />`
    - Component: `frontend/src/jaspenInterface/Workspace/ScoreDashboard.jsx`

## Data flow: API response → state/store → props → ScoreDashboard

### A) Finish & Analyze flow (new analysis)
1. **API call**
   - `Jaspen.analyzeFromConversation` in `frontend/src/jaspenInterface/Workspace/JaspenClient.jsx`
   - POSTs to `endpoints.analyze` (`/api/ai-agent/analyze`)
   - Returns: `{ analysis_result: data.analysis || data, analysis_id: data.analysis?.id || session_id }`

2. **Workspace mapping**
   - `onFinishAnalyze` in `frontend/src/jaspenInterface/Workspace/JaspenWorkspace.jsx`
   - `raw = data.analysis || data.analysis_result || data || {}`
   - **Shaping step** (maps only these keys explicitly):
     - `jaspen_score: raw.overall_score || raw.jaspen_score || 0`
     - `component_scores: raw.scores || raw.component_scores || {}`
     - `project_name: raw.name || raw.project_name || 'Jaspen Project'`
   - `normalize(mapped)` adds:
     - `score_category` based on `jaspen_score`
     - `financial_impact` with selected fields
     - `component_scores` normalized to the four keys
     - `risks` from `r.risks || r.top_risks || []`
     - **Preserves all original fields** via `...r`
   - Result stored in state:
     - `setAnalysisResult(result)`
     - `setScorecardSnapshots([{ ...result, id: baselineId, label: 'Baseline', isBaseline: true }])`

3. **Props into scorecard**
   - `activeScorecard` (priority):
     1. `selectedScorecardId` → `scorecardSnapshots` lookup
     2. `selectedVariant` (scenario A/B/C)
     3. `analysisResult`
   - Score tab passes:
     - `analysisResult={activeScorecard}`
     - `scorecardSnapshots`, `selectedScorecardId`, `baselineScorecardId`, etc.

### B) Restore session (thread + analyses response)
1. **API call**
   - `loadSessionById` in `frontend/src/jaspenInterface/Workspace/JaspenWorkspace.jsx`
   - GET `/api/ai-agent/threads/:id`

2. **Thread + analyses mapping**
   - If `data.thread` exists:
     - `latestAnalysis = analyses[0]`
     - **Shaping step** (drops unlisted keys if not present in `latestAnalysis`):
       - `result: { ...latestAnalysis, jaspen_score: latestAnalysis.overall_score, component_scores: latestAnalysis.scores || {} }`

3. **Hydration into UI**
   - On restore in `useEffect` and `handleSelectAnalysis`, scorecard is set with:
     - `normalizeAnalysis(fullScorecard)`
     - `setAnalysisResult(normalized)`

### C) History select (completed sessions)
1. **Source**
   - `analysisHistory` in `JaspenWorkspace`
   - Built from `fetchSessions()` + local storage
   - Each history item uses `session.result` (persisted backend result blob)

2. **Selection**
   - `handleSelectAnalysis(result)`
   - Uses `full = merged.result || merged` to find scorecard
   - **If missing detail sections**, calls `loadSessionById` and then `normalizeAnalysis(freshScorecard)`

## ScoreDashboard inputs (exact fields used)
Component: `frontend/src/jaspenInterface/Workspace/ScoreDashboard.jsx`

`result = selectedSnapshot || analysisResult || {}`

Fields read:
- `jaspen_score` → top score display
- `score_category` → badge label
- `component_scores` → component breakdown
- `financial_impact` → summary impacts
- `key_insights` → summary list
- `top_risks` or `risks` → risk list
- `recommendations` → recommendation list
- `metrics` → top 3 “dynamic metrics”
- `before_after_financials.before` / `.after` → before/after table
- `investment_analysis` → investment table
- `npv_irr_analysis` → NPV/IRR table
- `valuation` → valuation table
- `decision_framework` or `strategic_decision_framework` → decision checklist
- `project_name` (fallbacks via `result.compat.title`)

Decision Framework fields used (table rows):
- `acceptable_payback`
- `irr_above_hurdle`
- `npv_positive`
- `strategic_alignment`
- `robust_sensitivity`
- `overall_recommendation`

## Where analysis is shaped/filtered (likely reason only overall score shows)
1. **Finish & Analyze mapping**
   - `JaspenWorkspace.jsx` → `onFinishAnalyze` builds `mapped` from `raw`:
     - Explicitly maps `overall_score` → `jaspen_score`
     - Explicitly maps `scores` → `component_scores`
     - If backend returns a nested `analysis` object with detail sections under another key, those details will not be picked up unless they’re already at the top level of `raw`.

2. **Thread + analyses mapping**
   - `JaspenWorkspace.jsx` → `loadSessionById`
     - For new API format (`data.thread` + `data.analyses`), it sets:
       - `result: { ...latestAnalysis, jaspen_score: latestAnalysis.overall_score, component_scores: latestAnalysis.scores || {} }`
     - If `latestAnalysis` only contains `overall_score`/`scores` (and **not** the detailed sections like `investment_analysis`, `npv_irr_analysis`, `decision_framework`, `metrics`), then the UI will only have `jaspen_score` and `component_scores` to render.

3. **Normalization preserves but doesn’t invent**
   - `normalizeAnalysis(raw)` keeps all original fields via `...raw` but only **fills in**:
     - `jaspen_score`, `score_category`, `component_scores`, `financial_impact`, `project_name`, `risks`
   - If the incoming analysis blob lacks sections, the ScoreDashboard tables won’t render.

## Quick diagnosis summary
- The **Score tab** uses `ScoreDashboard` (`frontend/src/jaspenInterface/Workspace/ScoreDashboard.jsx`).
- `ScoreDashboard` expects detailed sections (`decision_framework`, `investment_analysis`, `npv_irr_analysis`, `valuation`, `before_after_financials`, `metrics`).
- The **most likely reason only `overall_score` displays** is that the API response being placed in `analysisResult` only includes `overall_score`/`scores`, while the detailed sections are missing or live under a different key that’s not being mapped.
- The main shaping points that can drop fields are:
  - `onFinishAnalyze` mapped fields
  - `loadSessionById` when reading `data.thread`/`data.analyses`

## Next places to inspect if needed
- Backend payloads for `/api/ai-agent/analyze` and `/api/ai-agent/threads/:id` to confirm where detailed sections live.
- If details are present under a different key, we should extend the mapping in `onFinishAnalyze` and/or `loadSessionById` to preserve them.
