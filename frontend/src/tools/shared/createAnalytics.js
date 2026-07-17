// =====================================================
// Shared analytics factory for Jaspen utilities.
// Each tool creates its own instance with a unique lead-source identifier so
// one contact can carry activity across every utility. Transport-agnostic:
// events go to window.dataLayer (GTM/GA4) and a DOM CustomEvent; dev logs to
// console. Analytics must never break the calculator.
// =====================================================

export const EVENTS = {
  UTILITY_VIEWED: 'utility_view',
  CALCULATOR_STARTED: 'calculator_started',
  STEP_COMPLETED: 'step_completed',
  BENCHMARK_OVERRIDDEN: 'benchmark_overridden',
  BENCHMARK_RESTORED: 'benchmark_restored',
  CALCULATOR_COMPLETED: 'calculator_completed',
  RESULTS_VIEWED: 'results_viewed',
  METHODOLOGY_VIEWED: 'methodology_viewed',
  COMPOSITION_VIEWED: 'composition_viewed',
  WHY_CHANGED_VIEWED: 'why_changed_viewed',
  SAVE_CTA_CLICKED: 'save_estimate_cta_clicked',
  SIGNUP_COMPLETED: 'signup_completed_from_utility',
  ESTIMATE_SAVED: 'estimate_saved',
  JASPEN_CTA_CLICKED: 'jaspen_product_cta_clicked',
  STEP_ABANDONED: 'step_abandoned',
  ERROR: 'utility_error',
};

function safeWindow() {
  return typeof window !== 'undefined' ? window : null;
}

/**
 * @param {string} source  unique lead-source identifier, e.g. "mortgage_calculator_utility"
 */
export function createAnalytics(source) {
  const track = (event, payload = {}) => {
    const w = safeWindow();
    const detail = { event, source, ts: Date.now(), ...payload };
    if (!w) return detail;
    try {
      w.dataLayer = w.dataLayer || [];
      w.dataLayer.push(detail);
      w.dispatchEvent(new CustomEvent('jaspen:analytics', { detail }));
    } catch {
      /* never break the utility */
    }
    if (process.env.NODE_ENV !== 'production') {
      // eslint-disable-next-line no-console
      console.debug(`[${source}]`, event, detail);
    }
    return detail;
  };

  return {
    source,
    EVENTS,
    track,
    utilityViewed: () => track(EVENTS.UTILITY_VIEWED),
    calculatorStarted: () => track(EVENTS.CALCULATOR_STARTED),
    stepCompleted: (stepId, index) => track(EVENTS.STEP_COMPLETED, { stepId, index }),
    benchmarkOverridden: (key, benchmarkId) => track(EVENTS.BENCHMARK_OVERRIDDEN, { key, benchmarkId }),
    benchmarkRestored: (key) => track(EVENTS.BENCHMARK_RESTORED, { key }),
    calculatorCompleted: (summary) => track(EVENTS.CALCULATOR_COMPLETED, summary),
    resultsViewed: (summary) => track(EVENTS.RESULTS_VIEWED, summary),
    methodologyViewed: () => track(EVENTS.METHODOLOGY_VIEWED),
    compositionViewed: () => track(EVENTS.COMPOSITION_VIEWED),
    whyChangedViewed: () => track(EVENTS.WHY_CHANGED_VIEWED),
    saveCtaClicked: () => track(EVENTS.SAVE_CTA_CLICKED),
    signupCompleted: () => track(EVENTS.SIGNUP_COMPLETED),
    estimateSaved: (mode) => track(EVENTS.ESTIMATE_SAVED, { mode }),
    jaspenCtaClicked: (target) => track(EVENTS.JASPEN_CTA_CLICKED, { target }),
    stepAbandoned: (stepId, index) => track(EVENTS.STEP_ABANDONED, { stepId, index }),
    error: (context, message) => track(EVENTS.ERROR, { context, message: String(message || '') }),
  };
}
