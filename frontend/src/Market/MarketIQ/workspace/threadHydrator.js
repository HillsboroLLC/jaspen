export function hydrateThreadFromBundle(bundle) {
  const threadId = bundle?.thread_id || bundle?.threadId || null;

  const messages = Array.isArray(bundle?.messages) ? bundle.messages : [];
  const scenarios = Array.isArray(bundle?.scenarios) ? bundle.scenarios : [];

  const adoptedAnalysisId = bundle?.adopted_analysis_id ?? null;
  const currentAnalysisId = bundle?.current_analysis_id ?? bundle?.analysis_id ?? null;
  const baselineAnalysisId = bundle?.baseline_analysis_id ?? null;

  const scorecard =
    bundle?.current_scorecard ??
    bundle?.baseline_scorecard ??
    bundle?.analysis_result ??
    null;

  const hasScorecard = !!scorecard;
  const readyForTabs = hasScorecard;

  return {
    threadId,
    messages,
    scenarios,
    adoptedAnalysisId,
    currentAnalysisId,
    baselineAnalysisId,
    scorecard,
    hasScorecard,
    readyForTabs,
    rawBundle: bundle,
  };
}
